"""Confirmed actual costs only; unknown costs keep cumulative returns provisional."""
import datetime as dt
import json
from decimal import Decimal
from pathlib import Path

COSTS = Path('/opt/kiwoom/state/automatic-execution-costs.json')

def read_costs(path=COSTS):
    try:
        data = json.loads(Path(path).read_text())
        if data.get('schema_version') != 1 or not isinstance(data.get('orders'), list):
            raise ValueError('cost_schema')
        seen = set()
        for record in data['orders']:
            key = (record['market'], record['strategy'], record['intent_id'])
            if key in seen:
                raise ValueError('duplicate_cost_identity')
            seen.add(key)
        return data['orders'], None
    except (OSError, ValueError, KeyError, TypeError):
        return [], '확인된 비용 파일을 읽거나 검증하지 못했습니다.'

def confirmed_cost(row, payload, records):
    matches = [r for r in records if (r.get('market'), r.get('strategy'), r.get('intent_id')) == (row['market'], row['strategy'], row['id'])]
    if len(matches) != 1:
        return None
    r = matches[0]
    try:
        date = dt.datetime.fromisoformat(row['created']).astimezone(dt.timezone(dt.timedelta(hours=9))).strftime('%Y%m%d')
        expected = dict(order_number=str(row['number']), trade_date=date, exchange=payload['exchange'], code=payload['code'], side=payload['side'], currency='KRW' if row['market'] == 'KR' else 'USD')
        if any(r.get(k) != v for k, v in expected.items()) or r['source'] not in ('ka10076', 'kt00015'):
            return None
        if int(r['filled_quantity']) != row['filled'] or Decimal(str(r['average'])) != Decimal(row['average']):
            return None
        fee, tax = (Decimal(str(r[k])) for k in ('fee', 'tax'))
        if not all(v.is_finite() and v >= 0 for v in (fee, tax)):
            return None
        # Partial/accepted observations are actual cost snapshots, not final coverage.
        final = r.get('provisional') is False and row['status'] in ('filled', 'cancelled') and r.get('status') == row['status']
        return fee, tax, final
    except (ValueError, KeyError, TypeError, ArithmeticError):
        return None

def calculate(rows, positions, market, strategy, records, cost_error=None):
    selected = [r for r in rows if r['market'] == market and r['strategy'] == strategy]
    held = {}; buys = realized = fee_total = tax_total = buy_cost = sell_cost = Decimal(0)
    filled_orders = confirmed = pending = closed = wins = 0
    try:
        for row in sorted(selected, key=lambda r: r['id']):
            if row['status'] in ('unknown', 'reconcile_error') or row['filled'] != row['applied']:
                raise ValueError('unconfirmed_fill')
            qty = row['applied']
            if not qty:
                continue
            p = json.loads(row['payload']); price = Decimal(row['average']); key = (p['exchange'], p['code'])
            if qty < 1 or qty > int(p['quantity']) or not price.is_finite() or price <= 0:
                raise ValueError('fill_price')
            filled_orders += 1
            cost = confirmed_cost(row, p, records) if not cost_error else None
            if cost is None:
                expense = Decimal(0)  # arithmetic only; coverage explicitly remains unknown
                pending += 1
            else:
                fee, tax, final = cost; expense = fee + tax; fee_total += fee; tax_total += tax
                confirmed += 1; pending += int(not final)
            if p['side'] == 'buy':
                if key in held:
                    raise ValueError('overlapping_buy')
                buys += price * qty; buy_cost += expense
                held[key] = dict(price=price, quantity=qty, cost=expense, cycle_pnl=-expense)
            elif p['side'] == 'sell':
                lot = held[key]
                if qty > lot['quantity']:
                    raise ValueError('unowned_sell')
                allocated = lot['cost'] * Decimal(qty) / Decimal(lot['quantity'])
                gross = (price - lot['price']) * qty
                realized += gross - allocated - expense; sell_cost += expense
                lot['cycle_pnl'] += gross - expense
                lot['cost'] -= allocated; lot['quantity'] -= qty
                if not lot['quantity']:
                    closed += 1; wins += int(lot['cycle_pnl'] > 0); del held[key]
            else:
                raise ValueError('side')
        current = {(p['exchange'], p['code']): p for p in positions if p.get('strategy') == strategy}
        if set(current) != set(held):
            raise ValueError('holdings_mismatch')
        unrealized = Decimal(0)
        for key, lot in held.items():
            p = current[key]; last = Decimal(str(p['last_price']))
            if p['quantity'] != lot['quantity'] or Decimal(str(p['entry_price'])) != lot['price'] or not last.is_finite() or last <= 0:
                raise ValueError('valuation_mismatch')
            unrealized += (last - lot['price']) * lot['quantity'] - lot['cost']
        total = realized + unrealized
        return dict(available=True, provisional=bool(pending), costs_included=not pending, confirmed_costs_included=True,
                    pending_cost_orders=pending, confirmed_cost_orders=confirmed, filled_orders=filled_orders,
                    coverage_complete=not pending, cost_error=cost_error, denominator_basis='gross_confirmed_buy_amount',
                    win_rate_basis='closed_buy_cycles_after_confirmed_actual_costs', cumulative_buy_amount=float(buys),
                    confirmed_fee=float(fee_total), confirmed_tax=float(tax_total), confirmed_buy_cost=float(buy_cost),
                    confirmed_sell_cost=float(sell_cost), realized_pnl=float(realized), unrealized_pnl=float(unrealized),
                    total_pnl=float(total), return_pct=float(total / buys * 100) if buys else None,
                    winning_trades=wins, closed_trades=closed, win_rate_pct=wins / closed * 100 if closed else None)
    except (ValueError, KeyError, TypeError, ArithmeticError):
        return dict(available=False, provisional=True, costs_included=False, reason='실제 체결·보유 기록을 확인한 뒤 순성과를 계산합니다.')

def cumulative(db, market, strategy, positions, path=COSTS):
    records, error = read_costs(path)
    rows = [dict(r) for r in db.execute('SELECT * FROM intents WHERE market=? AND strategy=? ORDER BY id', (market, strategy))]
    return calculate(rows, positions, market, strategy, records, error)
