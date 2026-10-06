"""Read-only broker cost snapshots; this module has no submission/control path."""
import datetime as dt
from decimal import Decimal
import fcntl
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time

ROOT = Path('/opt/kiwoom')
COSTS = ROOT / 'state/automatic-execution-costs.json'
DB = ROOT / 'state/auto-trading.sqlite3'
KST = dt.timezone(dt.timedelta(hours=9))

def number(value):
    value = Decimal(str(value).strip().replace(',', ''))
    if not value.is_finite():
        raise ValueError('invalid_number')
    return value

def date_of(row):
    return dt.datetime.fromisoformat(row['created']).astimezone(KST).strftime('%Y%m%d')

def record(row, payload, fee, tax, source, now):
    if fee < 0 or tax < 0:
        raise ValueError('negative_cost')
    return dict(intent_id=row['id'], order_number=str(row['number']), trade_date=date_of(row),
                market=row['market'], strategy=row['strategy'], exchange=payload['exchange'], code=payload['code'],
                side=payload['side'], filled_quantity=row['filled'], average=str(number(row['average'])),
                fee=str(fee), tax=str(tax), currency='KRW', source=source, queried_at=now,
                status=row['status'], provisional=row['status'] not in ('filled', 'cancelled'))

def today_records(intents, reports, today, now):
    output = []; used = set()
    for row in intents:
        if row['market'] != 'KR' or date_of(row) != today or row['filled'] <= 0:
            continue
        p = json.loads(row['payload'])
        hits = [(i, r) for i, r in enumerate(reports) if str(r.get('ord_no', '')).lstrip('0') == str(row['number']).lstrip('0')
                and str(r.get('stk_cd', '')).removeprefix('A') == p['code']
                and r.get('io_tp_nm') == ('+매수' if p['side'] == 'buy' else '-매도')
                and str(r.get('stex_tp')) == {'KRX': '1', 'NXT': '2'}.get(p['exchange'], 'invalid')]
        try:
            if len(hits) != 1 or row['status'] in ('unknown', 'reconcile_error'):
                continue
            i, r = hits[0]
            if i in used or number(r['cntr_qty']) != row['filled'] or row['filled'] != row['applied'] or number(r['cntr_pric']) != number(row['average']):
                continue
            output.append(record(row, p, number(r['tdy_trde_cmsn']), number(r['tdy_trde_tax']), 'ka10076', now))
            used.add(i)
        except (ValueError, KeyError, TypeError, ArithmeticError):
            continue
    return output

def past_records(intents, fills, confirmations, transactions, dates, now):
    # Broker fills include manual orders. No amount allocation across ambiguous groups.
    orders = {}; blocked = set(); seen = set()
    for r in fills:
        key = (r['_query_date'], str(r['ord_no']).lstrip('0'))
        fill_id = (key, r.get('cntr_no'))
        try:
            if not r.get('cntr_no') or fill_id in seen:
                raise ValueError('duplicate_fill')
            seen.add(fill_id)
            qty, price = number(r['cntr_qty']), number(r['cntr_uv'])
            side = 'buy' if '매수' in r['io_tp_nm'] else 'sell' if '매도' in r['io_tp_nm'] else None
            exchange = r['dmst_stex_tp']
            if qty <= 0 or qty != qty.to_integral_value() or price <= 0 or side is None or exchange not in ('KRX', 'NXT'):
                raise ValueError('fill_identity')
            identity = (exchange, str(r['stk_cd']).removeprefix('A'), side)
            lot = orders.setdefault(key, dict(identity=identity, qty=Decimal(0), amount=Decimal(0)))
            if lot['identity'] != identity:
                raise ValueError('inconsistent_order')
            lot['qty'] += qty; lot['amount'] += qty * price
        except (ValueError, KeyError, TypeError, ArithmeticError):
            blocked.add(key)
    canonical = {}
    for r in confirmations:
        canonical.setdefault((r['_query_date'], str(r['ord_no']).lstrip('0')), []).append(r)
    for key, lot in orders.items():
        code = lot['identity'][1]
        if not code.startswith('*A'):
            continue
        candidates = canonical.get(key, [])
        try:
            if len(candidates) != 1:
                raise ValueError('canonical_ambiguous')
            r = candidates[0]; confirmed = str(r['stk_cd']).removeprefix('A')
            side = 'buy' if '매수' in r['io_tp_nm'] else 'sell' if '매도' in r['io_tp_nm'] else None
            if code != '*A' + confirmed or r['dmst_stex_tp'] != lot['identity'][0] or side != lot['identity'][2] or number(r['cntr_qty']) != lot['qty'] or number(r['cntr_uv']) * lot['qty'] != lot['amount']:
                raise ValueError('canonical_not_exact')
            lot['identity'] = (lot['identity'][0], confirmed, side)
        except (ValueError, KeyError, TypeError, ArithmeticError):
            blocked.add(key)
    order_groups = {}; tx_groups = {}; tainted = set()
    for (date, no), lot in orders.items():
        if (date, no) not in blocked:
            order_groups.setdefault((date, *lot['identity'], lot['qty'], lot['amount']), []).append(no)
    for t in transactions:
        date = t.get('cntr_dt'); code = str(t.get('stk_cd', '')).removeprefix('A')
        try:
            side = 'buy' if '매수' in t['rmrk_nm'] else 'sell' if '매도' in t['rmrk_nm'] else None
            qty, amount = number(t['trde_qty_jwa_cnt']), number(t['trde_amt'])
            if date not in dates:
                continue
            if side is None or t['stex_cd'] not in ('KRX', 'NXT') or qty <= 0 or qty != qty.to_integral_value() or amount <= 0 or amount != amount.to_integral_value() or str(t.get('orig_deal_no', '')).strip('0 '):
                raise ValueError('transaction_not_exact')
            key = (date, t['stex_cd'], code, side, qty, amount)
            tx_groups.setdefault(key, []).append(t)
        except (ValueError, KeyError, TypeError, ArithmeticError):
            if date in dates:
                tainted.add((date, code))
    output = []
    for row in intents:
        try:
            if row['market'] != 'KR' or date_of(row) not in dates or row['filled'] <= 0 or row['filled'] != row['applied'] or row['status'] in ('unknown', 'reconcile_error'):
                continue
            p = json.loads(row['payload']); date = date_of(row); no = str(row['number']).lstrip('0')
            lot = orders[(date, no)]
            if (date, no) in blocked or (date, p['code']) in tainted or lot['identity'] != (p['exchange'], p['code'], p['side']) or lot['qty'] != row['filled'] or lot['amount'] != number(row['average']) * row['filled']:
                continue
            key = (date, *lot['identity'], lot['qty'], lot['amount'])
            links = [r for r in intents if r['market'] == 'KR' and date_of(r) == date and str(r['number']).lstrip('0') == no]
            if len(order_groups.get(key, [])) != 1 or len(tx_groups.get(key, [])) != 1 or len(links) != 1:
                continue
            t = tx_groups[key][0]
            cost = record(row, p, number(t['cmsn']), number(t['trde_agri_tax']), 'kt00015', now)
            cost.update(transaction_number=t['trde_no'], transaction_trade_date=t['trde_dt'], execution_date=t['cntr_dt'], gross_filled_amount=str(lot['amount']), matching_method='full_paginated_broker_fills_and_unique_exact_transaction_key')
            output.append(cost)
        except (ValueError, KeyError, TypeError, ArithmeticError):
            continue
    return output

def merge_records(existing, incoming):
    key = lambda r: (r['market'], r['strategy'], r['intent_id'])
    saved = {key(r): r for r in existing}
    if len(saved) != len(existing):
        raise ValueError('duplicate_existing_cost')
    for r in incoming:
        old = saved.get(key(r))
        if old:
            if any(old[k] != r[k] for k in ('order_number', 'trade_date', 'exchange', 'code', 'side', 'currency')) or r['filled_quantity'] < old['filled_quantity']:
                raise ValueError('cost_identity_conflict')
            if all(old.get(k) == v for k, v in r.items() if k != 'queried_at'):
                continue
        saved[key(r)] = r
    return sorted(saved.values(), key=lambda r: (r['trade_date'], r['market'], r['strategy'], r['intent_id']))

def store(path, incoming):
    path = Path(path)
    if path.is_symlink():
        raise ValueError('cost_symlink')
    lock = path.with_name('.automatic-execution-costs.lock')
    fd = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'r+') as guard:
        os.fchmod(guard.fileno(), 0o600); fcntl.flock(guard, fcntl.LOCK_EX)
        data = json.loads(path.read_text()) if path.exists() else dict(schema_version=1, orders=[])
        if data.get('schema_version') != 1:
            raise ValueError('cost_schema')
        orders = merge_records(data['orders'], incoming)
        if orders == data['orders']:
            return len(orders)
        encoded = json.dumps(dict(schema_version=1, orders=orders, updated_at=dt.datetime.now(KST).isoformat()), ensure_ascii=False, indent=2).encode()
        fd, name = tempfile.mkstemp(prefix='.automatic-costs-', dir=path.parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, 'wb') as f:
                f.write(encoded); f.flush(); os.fsync(f.fileno())
            os.replace(name, path)
            directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(name):
                os.unlink(name)
        return len(orders)

def run():
    import trading_api
    from auto_performance_net import confirmed_cost, read_costs
    with sqlite3.connect('file:' + str(DB) + '?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        intents = [dict(r) for r in db.execute('SELECT * FROM intents WHERE applied>0')]
    known, error = read_costs(COSTS)
    if error:
        raise ValueError('existing_costs_unreadable')
    now = dt.datetime.now(KST); today = now.strftime('%Y%m%d')
    client = trading_api.client('real')
    allowed = {'ka10076', 'kt00009', 'kt00007', 'kt00015'}
    def pages(api, body, key):
        if api not in allowed:
            raise ValueError('non_read_api')
        rows = []; continuation = None
        for _ in range(100):
            time.sleep(.5)
            data, nxt = trading_api.call(client, api, '/api/dostk/acnt', body, continuation)
            if str(data.get('return_code', '0')) != '0' or not isinstance(data.get(key), list):
                raise ValueError('broker_schema')
            rows.extend(data[key])
            if nxt[0] != 'Y':
                return rows
            if not nxt[1] or nxt == continuation:
                raise ValueError('incomplete_pagination')
            continuation = nxt
        raise ValueError('incomplete_pagination')
    reports = pages('ka10076', dict(stk_cd='', qry_tp='0', sell_tp='0', ord_no='', stex_tp='0'), 'cntr')
    incoming = today_records(intents, reports, today, now.isoformat())
    # Persist today's verified data before a historical query failure can occur.
    total = store(COSTS, incoming)
    pending = [r for r in intents if r['market'] == 'KR' and date_of(r) < today and (confirmed_cost(r, json.loads(r['payload']), known) is None or not confirmed_cost(r, json.loads(r['payload']), known)[2])]
    dates = sorted({date_of(r) for r in pending})
    past_count = 0
    if dates:
        fills = []; confirmations = []
        for date in dates:
            body = dict(ord_dt=date, stk_bond_tp='1', mrkt_tp='0', sell_tp='0', qry_tp='1', stk_cd='', fr_ord_no='', dmst_stex_tp='%')
            rows = pages('kt00009', body, 'acnt_ord_cntr_prst_array')
            for row in rows: row['_query_date'] = date
            fills.extend(rows)
            body = dict(ord_dt=date, qry_tp='1', stk_bond_tp='1', sell_tp='0', stk_cd='', fr_ord_no='', dmst_stex_tp='%')
            rows = pages('kt00007', body, 'acnt_ord_cntr_prps_dtl')
            for row in rows: row['_query_date'] = date
            confirmations.extend(rows)
        transactions = pages('kt00015', dict(strt_dt=dates[0], end_dt=today, tp='3', stk_cd='', crnc_cd='KRW', gds_tp='1', frgn_stex_code='', dmst_stex_tp='%', qry_sort_tp='2'), 'trst_ovrl_trde_prps_array')
        historical = past_records(intents, fills, confirmations, transactions, dates, now.isoformat())
        past_count = len(historical); total = store(COSTS, historical)
    print(json.dumps(dict(today_verified=len(incoming), past_verified=past_count, stored_rows=total, unknown_costs_not_assumed_zero=True)))

if __name__ == '__main__':
    try:
        run()
    except Exception as error:
        # Broker exceptions may contain raw responses. Never log their text.
        print(json.dumps(dict(status='cost_collection_failed', error_class=type(error).__name__)))
        raise SystemExit(1)
