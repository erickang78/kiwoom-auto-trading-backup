"""Read-only realized virtual sales, using original entry cost and KST sale date."""
import datetime as dt
import sqlite3
from decimal import Decimal
from zoneinfo import ZoneInfo
from real_profit_report import summarize
from signal_validation import portfolio_id, STRATEGIES, upgrade


def build(db, market, strategy='all'):
    ids = [portfolio_id(market, s) for s in STRATEGIES if strategy in ('all', s)]
    if not ids:
        raise ValueError('invalid_strategy')
    sales, warnings = [], []
    rows = db.execute('SELECT id,data FROM events WHERE portfolio IN (' + ','.join('?' for _ in ids) + ') ORDER BY id', ids)
    for row in rows:
        try:
            event = upgrade(row['data'])
            if event['kind'] != 'SELL':
                continue
            qty = event['quantity']
            entry = Decimal(str(event['entry_price']))
            price = Decimal(str(event['reference_price']))
            if type(qty) is not int or qty <= 0 or not entry.is_finite() or not price.is_finite() or entry <= 0 or price <= 0:
                raise ValueError('invalid_sale')
            stamp = dt.datetime.fromisoformat(event['at'])
            if stamp.tzinfo is None:
                raise ValueError('missing_timezone')
            cost, proceeds = entry * qty, price * qty
            sales.append(dict(day=stamp.astimezone(ZoneInfo('Asia/Seoul')).date().isoformat(), cost=cost, proceeds=proceeds, pnl=proceeds-cost, quantity=qty))
        except (ValueError, TypeError, KeyError, ArithmeticError):
            warnings.append(row['id'])
            break
    return summarize(sales, warnings, market, strategy, 'virtual_sale_date')


def read_report(path, market, strategy='all'):
    with sqlite3.connect('file:'+str(path)+'?mode=ro', uri=True, timeout=10) as db:
        db.row_factory = sqlite3.Row
        return build(db, market, strategy)
