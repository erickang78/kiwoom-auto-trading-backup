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
        return build(db,market,strategy)
