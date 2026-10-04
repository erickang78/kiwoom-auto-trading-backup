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
    return str(int(value)) if value.isdigit() and int(value) > 0 else ''


def date(value):
    value = str(value or '')
    compact = re.sub(r'[-/]', '', value)
    if re.fullmatch(r'\d{8}', compact):
        return compact
    return ''


def ledger(state):
    index, unresolved = {}, set()
    for filename, table, origin in [('auto-trading.sqlite3', 'intents', 'automatic'),
                                    ('manual-orders.sqlite3', 'orders', 'manual')]:
        with closing(sqlite3.connect((state / filename).as_uri() + '?mode=ro', uri=True, timeout=2)) as db:
            db.row_factory = sqlite3.Row
            for row in db.execute('SELECT * FROM ' + table):
                if row['status'] == 'preview':
                    continue
                payload = json.loads(row['payload'])
                mode = payload.get('mode', 'real')
                market = payload['market']
                created = (dt.datetime.fromisoformat(row['created']) if origin == 'automatic'
                           else dt.datetime.fromtimestamp(row['created'], dt.timezone.utc))
                day = created.astimezone(KST).strftime('%Y%m%d')
                ident = number(row['number'] if origin == 'automatic' else json.loads(row['result']).get('order_number'))
                if not ident:
                    if origin == 'automatic' and row['status'] in ('unknown', 'reconcile_error'):
                        unresolved.add((mode, market))
                    continue
                key = mode, market, day, ident
                index.setdefault(key, set()).add((origin, payload['code'].removeprefix('A') if market == 'KR' else payload['code']))
    return index, unresolved


def annotate_snapshot(body, state=STATE):
    if not isinstance(body, dict) or body.get('mode') not in ('REAL_READ_ONLY', 'MOCK_READ_ONLY'):
        return body
    mode = 'real' if body['mode'] == 'REAL_READ_ONLY' else 'mock'
    try:
        index, unresolved = ledger(state)
        healthy = True
    except (OSError, sqlite3.Error, ValueError, KeyError, TypeError, OverflowError):
        index, unresolved, healthy = {}, set(), False
    # These endpoints query today's orders; explicit order dates take precedence.
    retrieved = dt.datetime.fromisoformat(body['retrieved_at']).astimezone(KST).strftime('%Y%m%d')
    for market, section in [('KR', body), ('US', body.get('us')), ('GOLD', body.get('gold'))]:
        if not isinstance(section, dict):
            continue
        for field in ('executions', 'pending_orders'):
            for row in section.get(field, []):
                day = date(row.get('ord_dt')) if row.get('ord_dt') else retrieved
                ident = number(row.get('ord_no'))
                code = str(row.get('stk_cd', '')).strip()
                if market == 'KR':
                    code = code.removeprefix('A')
                matches = index.get((mode, market, day, ident), set())
                if healthy and day and ident and len(matches) == 1 and next(iter(matches))[1] == code:
                    source = next(iter(matches))[0]
                elif healthy and day and ident and not matches and (mode, market) not in unresolved:
                    # Orders outside this program's automatic ledger were placed manually.
                    source = 'manual'
                else:
                    source = 'unknown'
                row['trading_source'] = source
    return body

