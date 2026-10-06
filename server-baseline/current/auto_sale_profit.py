"""Read-only per-sale gross profit from the full automatic fill ledger."""
import json
from decimal import Decimal


def sale_profits(db, market, strategy):
    lots, blocked, results = {}, set(), {}
    for row in db.execute('SELECT * FROM intents WHERE market=? AND strategy=? ORDER BY id', (market, strategy)):
        key = None
        try:
            payload = json.loads(row['payload'])
            key = (payload['exchange'], payload['code'])
            side = payload['side']
            qty = int(row['applied'])
            if side == 'sell':
                results[row['id']] = dict(available=False, costs_included=False, currency='KRW' if market == 'KR' else 'USD')
            if row['status'] in ('unknown', 'reconcile_error') or qty != row['filled']:
                blocked.add(key)
                continue
            if not qty:
                continue
            price = Decimal(str(row['average']))
            if qty < 1 or qty > int(payload['quantity']) or not price.is_finite() or price <= 0:
                blocked.add(key)
                continue
            if key in blocked:
                continue
            if side == 'buy':
                if key in lots:
                    blocked.add(key)
                    continue
                lots[key] = (qty, price)
            elif side == 'sell':
                held, entry = lots[key]
                if qty > held:
                    blocked.add(key)
                    continue
                results[row['id']].update(available=True, amount=float((price-entry)*qty), filled_quantity=qty, average_buy_price=float(entry))
                if held == qty:
                    del lots[key]
                else:
                    lots[key] = (held-qty, entry)
            else:
                blocked.add(key)
        except (ValueError, KeyError, TypeError, ArithmeticError):
            # A malformed row cannot support subsequent matching.
            if key is not None:
                blocked.add(key)
            else:
                return {}
    return results
