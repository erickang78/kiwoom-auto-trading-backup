"""Read-only realized automatic-trading profit, grouped by final fill confirmation day."""
import datetime as dt
import json
import sqlite3
from decimal import Decimal
from zoneinfo import ZoneInfo


def build(db, market, strategy='all'):
    held = {}; sales = []; warnings = []
    rows = db.execute('SELECT * FROM intents WHERE market=? ORDER BY id', (market,)).fetchall()
    def amount(value):
        v = Decimal(str(value))
        if not v.is_finite() or v < 0: raise ValueError('amount')
        return v
    for r in rows:
        if strategy != 'all' and r['strategy'] != strategy: continue
        try:
            if r['status'] in ('unknown', 'reconcile_error'): raise ValueError('unverified')
            if r['filled'] != r['applied']: raise ValueError('unverified')
            qty = r['applied']
            if not qty: continue
            p = json.loads(r['payload']); key = (r['strategy'], p['exchange'], p['code'])
            price = amount(r['average'])
            if not isinstance(qty, int) or qty < 1 or qty > int(p['quantity']) or price <= 0: raise ValueError('quantity')
            if p['side'] == 'buy':
                if key in held: raise ValueError('duplicate_buy')
                held[key] = [qty, price]
            elif p['side'] == 'sell':
                lot = held.get(key)
                if lot is None or qty > lot[0]: raise ValueError('missing_cost')
                stamp = dt.datetime.fromisoformat(r['updated'])
                if stamp.tzinfo is None: raise ValueError('time')
                day = stamp.astimezone(ZoneInfo('Asia/Seoul')).date().isoformat()
                cost = lot[1] * qty; proceeds = price * qty
                sales.append(dict(day=day, cost=cost, proceeds=proceeds, pnl=proceeds-cost, quantity=qty))
                lot[0] -= qty
                if not lot[0]: del held[key]
            else: raise ValueError('side')
        except (ValueError, TypeError, KeyError, ArithmeticError):
            warnings.append(r['id'])
            # An incomplete ledger cannot safely produce a definitive total.
            break
    return summarize(sales, warnings, market, strategy)


def summarize(sales, warnings, market, strategy, basis="final_fill_confirmation_date"):
    def aggregate(items, label):
        cost=sum((x['cost'] for x in items), Decimal(0)); proceeds=sum((x['proceeds'] for x in items),Decimal(0)); pnl=proceeds-cost
        return dict(period=label,cost=float(cost),proceeds=float(proceeds),pnl=float(pnl),return_pct=float(pnl/cost*100) if cost else None,sell_orders=len(items),quantity=sum(x['quantity'] for x in items),wins=sum(x['pnl']>0 for x in items))
    groups={}
    for name,n in [('daily',10),('monthly',7),('yearly',4)]:
        buckets={}
        for sale in sales: buckets.setdefault(sale['day'][:n],[]).append(sale)
        groups[name]=[aggregate(buckets[k],k) for k in sorted(buckets,reverse=True)] if not warnings else []
    return dict(market=market,strategy=strategy,currency='KRW' if market=='KR' else 'USD',available=not warnings,unverified_orders=warnings,
                basis=basis,timezone='Asia/Seoul',costs_included=False,
                summary=aggregate(sales,'전체') if not warnings else None,**groups)


def read_report(path, market, strategy='all'):
    with sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True,timeout=10) as db:
        db.row_factory=sqlite3.Row
        db.execute('BEGIN')
        return build_net(db,market,strategy)


def build_net(db, market, strategy='all', records=None, cost_error=None):
    """Realized only: actual buy costs follow sold quantities; unsold costs stay out."""
    from auto_performance_net import confirmed_cost, read_costs
    if records is None:
        records, cost_error = read_costs()
    held = {}; sales = []; warnings = []
    for row in db.execute('SELECT * FROM intents WHERE market=? ORDER BY id', (market,)).fetchall():
        if strategy != 'all' and row['strategy'] != strategy:
            continue
        try:
            if row['status'] in ('unknown', 'reconcile_error') or row['filled'] != row['applied']:
                raise ValueError('unverified')
            qty = row['applied']
            if not qty:
                continue
            p = json.loads(row['payload']); price = Decimal(row['average'])
            if not isinstance(qty, int) or qty < 1 or qty > int(p['quantity']) or not price.is_finite() or price <= 0:
                raise ValueError('fill')
            key = (row['strategy'], p['exchange'], p['code'])
            expense = confirmed_cost(row, p, records) if not cost_error else None
            fee, tax = expense[:2] if expense else (Decimal(0), Decimal(0))
            pending = expense is None or not expense[2]
            identity = (row['market'], row['strategy'], row['id'])
            if p['side'] == 'buy':
                if key in held:
                    raise ValueError('duplicate_buy')
                held[key] = dict(quantity=qty, price=price, fee=fee, tax=tax, pending=pending, identity=identity, known=expense is not None)
            elif p['side'] == 'sell':
                lot = held[key]
                if qty > lot['quantity']:
                    raise ValueError('unowned_sell')
                stamp = dt.datetime.fromisoformat(row['updated'])
                if stamp.tzinfo is None:
                    raise ValueError('time')
                day = stamp.astimezone(ZoneInfo('Asia/Seoul')).date().isoformat()
                buy_fee = lot['fee'] * Decimal(qty) / Decimal(lot['quantity'])
                buy_tax = lot['tax'] * Decimal(qty) / Decimal(lot['quantity'])
                principal = lot['price'] * qty; proceeds = price * qty
                pending_ids = set(); confirmed_ids = set()
                if lot['pending']: pending_ids.add(lot['identity'])
                if pending: pending_ids.add(identity)
                if lot['known']: confirmed_ids.add(lot['identity'])
                if expense: confirmed_ids.add(identity)
                sales.append(dict(day=day, cost=principal, proceeds=proceeds,
                                  gross_pnl=proceeds-principal, pnl=proceeds-principal-buy_fee-buy_tax-fee-tax,
                                  buy_fee=buy_fee, buy_tax=buy_tax, sell_fee=fee, sell_tax=tax,
                                  quantity=qty, pending_ids=pending_ids, confirmed_ids=confirmed_ids))
                lot['quantity'] -= qty; lot['fee'] -= buy_fee; lot['tax'] -= buy_tax
                if not lot['quantity']:
                    del held[key]
            else:
                raise ValueError('side')
        except (ValueError, KeyError, TypeError, ArithmeticError):
            warnings.append(row['id']); break
    def aggregate(items, label):
        total = lambda key: sum((s[key] for s in items), Decimal(0))
        principal, proceeds, pnl = total('cost'), total('proceeds'), total('pnl')
        buy_cost = total('buy_fee') + total('buy_tax'); sell_cost = total('sell_fee') + total('sell_tax')
        pending_ids = set().union(*(s['pending_ids'] for s in items)) if items else set()
        confirmed_ids = set().union(*(s['confirmed_ids'] for s in items)) if items else set()
        return dict(period=label, cost=float(principal), proceeds=float(proceeds), pnl=float(pnl),
                    return_pct=float(pnl/principal*100) if principal else None,
                    gross_pnl=float(total('gross_pnl')), gross_cost=float(principal), gross_proceeds=float(proceeds),
                    net_acquisition_cost=float(principal+buy_cost), net_proceeds=float(proceeds-sell_cost),
                    allocated_buy_cost=float(buy_cost), confirmed_sell_cost=float(sell_cost),
                    confirmed_fee=float(total('buy_fee')+total('sell_fee')), confirmed_tax=float(total('buy_tax')+total('sell_tax')),
                    confirmed_cost=float(buy_cost+sell_cost), pending_cost_orders=len(pending_ids),
                    confirmed_cost_orders=len(confirmed_ids), provisional=bool(pending_ids), costs_included=not pending_ids,
                    sell_orders=len(items), quantity=sum(s['quantity'] for s in items), wins=sum(s['pnl']>0 for s in items))
    groups = {}
    for name, n in [('daily', 10), ('monthly', 7), ('yearly', 4)]:
        buckets = {}
        for sale in sales: buckets.setdefault(sale['day'][:n], []).append(sale)
        groups[name] = [aggregate(buckets[k], k) for k in sorted(buckets, reverse=True)] if not warnings else []
    summary = aggregate(sales, '전체') if not warnings else None
    return dict(market=market, strategy=strategy, currency='KRW' if market=='KR' else 'USD', available=not warnings,
                unverified_orders=warnings, basis='final_fill_confirmation_date', timezone='Asia/Seoul',
                costs_included=bool(summary and summary['costs_included']), confirmed_costs_included=True,
                provisional=bool(summary and summary['provisional']), pending_cost_orders=summary['pending_cost_orders'] if summary else None,
                denominator_basis='gross_sold_buy_principal', proceeds_basis='gross_proceeds_compatibility_use_net_proceeds',
                cost_error=cost_error, summary=summary, **groups)
