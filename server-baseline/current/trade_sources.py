"""Read-only origin labels for broker order rows; never submits or changes orders."""
from contextlib import closing
import datetime as dt
import json
from pathlib import Path
import re
import sqlite3

STATE = Path('/opt/kiwoom/state')
KST = dt.timezone(dt.timedelta(hours=9))


def number(value):
    value = str(value or '').strip()
    try:
        return str(int(value)) if re.fullmatch(r'[0-9]+', value) and int(value) > 0 else ''
    except ValueError:
        return ''


def date(value):
    value = str(value or '').strip()
    compact = re.sub(r'[-/]', '', value)
    if re.fullmatch(r'\d{8}|\d{4}-\d{2}-\d{2}|\d{4}/\d{2}/\d{2}', value):
        try:
            dt.datetime.strptime(compact, '%Y%m%d')
            return compact
        except ValueError:
            pass
    return ''


def stock_code(value, market):
    if not isinstance(value, str):
        return ''
    value = value.strip()
    return value.removeprefix('A') if market == 'KR' else value


def ledger(state):
    index = {}
    for filename, table, origin in [('auto-trading.sqlite3', 'intents', 'automatic'),
                                    ('manual-orders.sqlite3', 'orders', 'manual')]:
        with closing(sqlite3.connect((state / filename).as_uri() + '?mode=ro', uri=True, timeout=2)) as db:
            db.row_factory = sqlite3.Row
            for row in db.execute('SELECT * FROM ' + table):
                if row['status'] == 'preview':
                    continue
                payload = json.loads(row['payload'])
                mode = payload['mode']
                market = payload['market']
                created = (dt.datetime.fromisoformat(row['created']) if origin == 'automatic'
                           else dt.datetime.fromtimestamp(row['created'], dt.timezone.utc))
                if created.tzinfo is None:
                    raise ValueError('ambiguous_ledger_timezone')
                day = created.astimezone(KST).strftime('%Y%m%d')
                result = json.loads(row['result']) if origin == 'manual' else {}
                if not isinstance(result, dict):
                    raise ValueError('invalid_ledger_result')
                ident = number(row['number'] if origin == 'automatic' else result.get('order_number'))
                if not ident:
                    continue
                key = mode, market, day, ident
                confirmed = row['status'] in (('accepted', 'partial', 'filled', 'cancelled')
                                              if origin == 'automatic' else ('accepted',))
                # Manual creation is preview time, up to 120s before submission.
                # A preview spanning KST midnight cannot establish an order day.
                if origin == 'manual' and (created + dt.timedelta(seconds=120)).astimezone(KST).strftime('%Y%m%d') != day:
                    confirmed = False
                code = stock_code(payload['code'], market)
                # Keep duplicate records: even identical entries are ambiguous.
                index.setdefault(key, []).append((origin if confirmed else 'unknown', code))
    return index


def annotate_snapshot(body, state=STATE):
    if not isinstance(body, dict) or body.get('mode') not in ('REAL_READ_ONLY', 'MOCK_READ_ONLY'):
        return body
    mode = 'real' if body['mode'] == 'REAL_READ_ONLY' else 'mock'
    try:
        index = ledger(state)
    except (OSError, sqlite3.Error, ValueError, KeyError, TypeError, OverflowError):
        index = {}
    # Retrieval/browser time is not order-date evidence. An undated broker row
    # cannot be linked by number alone: order numbers can repeat on other days.
    for market, section in [('KR', body), ('US', body.get('us')), ('GOLD', body.get('gold'))]:
        if not isinstance(section, dict):
            continue
        for field in ('executions', 'pending_orders'):
            for row in section.get(field, []):
                day = date(row.get('ord_dt'))
                ident = number(row.get('ord_no'))
                code = stock_code(row.get('stk_cd'), market)
                matches = index.get((mode, market, day, ident), [])
                source = matches[0][0] if day and ident and code and len(matches) == 1 and matches[0][1] == code else 'unknown'
                row['trading_source'] = source
    return body
