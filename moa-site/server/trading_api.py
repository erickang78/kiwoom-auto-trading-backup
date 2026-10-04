"""Manual limit orders and US stock lookup. No automatic order submission."""
import datetime
import json
import re
import sqlite3
import time
import uuid
from decimal import Decimal
from pathlib import Path

DB = Path('/opt/kiwoom/state/manual-orders.sqlite3')
CACHE = {'at': 0, 'rows': []}


def client(mode='real'):
    from broker_read import Client
    from credentials import load_credentials
    if mode not in ('real', 'mock'):
        raise ValueError('invalid_mode')
    c = Client('https://api.kiwoom.com' if mode == 'real' else 'https://mockapi.kiwoom.com')
    c.authenticate(*load_credentials(Path('/opt/kiwoom/secrets/' + mode + '-credentials.json')))
    return c


def call(c, api, path, body, continuation=None):
    h = {'api-id': api, 'authorization': 'Bearer ' + c.token}
    if continuation:
        h.update({'cont-yn': continuation[0], 'next-key': continuation[1]})
    return c._post(path, body, h)


def us_search(query):
    if not isinstance(query, str) or not 1 <= len(query.strip()) <= 80:
        raise ValueError('invalid_query')
    if time.time() - CACHE['at'] > 3600:
        c, rows, continuation = client(), [], None
        for _ in range(100):
            data, nxt = call(c, 'usa10099', '/api/us/stkinfo', {'stex_tp': '%'}, continuation)
            rows.extend(data.get('list', []))
            if nxt[0] != 'Y':
                break
            if not nxt[1] or nxt == continuation:
                raise RuntimeError('invalid_pagination')
            continuation = nxt
            time.sleep(.3)
        else:
            raise RuntimeError('incomplete_stock_list')
        if not rows:
            raise RuntimeError('empty_stock_list')
        CACHE.update(at=time.time(), rows=rows)
    q = query.strip().casefold()
    rows = [x for x in CACHE['rows'] if any(q in str(x.get(k, '')).casefold() for k in ('stk_cd', 'stk_nm', 'stk_enm'))]
    rows.sort(key=lambda x: (str(x.get('stk_cd', '')).casefold() != q, str(x.get('stk_cd', ''))))
    return {'results': [{k: x.get(k, '') for k in ('stk_cd', 'stk_nm', 'stk_enm', 'stex_tp', 'mkgb')} for x in rows[:50]], 'total': len(rows)}


def us_quote(code, exchange):
    if not isinstance(code, str) or not re.fullmatch(r'[A-Z0-9.\-/]{1,12}', code) or exchange not in ('NA', 'ND', 'NY'):
        raise ValueError('invalid_stock')
    data, _ = call(client(), 'usa20100', '/api/us/mrkcond', {'stk_cd': code, 'stex_tp': exchange})
    keys = ('stk_cd', 'stk_nm', 'stk_enm', 'stex_tp', 'cur_prc', 'flu_rt', 'acc_trde_qty', 'base_close_pric', 'curr_unit')
    return {'quote': {k: data.get(k) for k in keys}, 'retrieved_at': datetime.datetime.now(datetime.timezone.utc).isoformat()}


def normalize_order(body):
    if not isinstance(body, dict):
        raise ValueError('invalid_order')
    mode, market, side = (body.get(k) for k in ('mode', 'market', 'side'))
    if mode not in ('mock', 'real') or market not in ('KR', 'US') or side not in ('buy', 'sell'):
        raise ValueError('invalid_order')
    if market == 'US' and mode != 'real':
        raise ValueError('us_real_only')
    code = body.get('code', '')
    if not isinstance(code, str) or not re.fullmatch(r'\d{6}' if market == 'KR' else r'[A-Z0-9.\-/]{1,12}', code):
        raise ValueError('invalid_stock')
    quantity, price = body.get('quantity'), body.get('price')
    if not isinstance(quantity, str) or not re.fullmatch(r'[1-9]\d{0,8}', quantity):
        raise ValueError('invalid_quantity')
    pattern = r'[1-9]\d{0,10}' if market == 'KR' else r'(?:0|[1-9]\d{0,6})(?:\.\d{1,4})?'
    if not isinstance(price, str) or not re.fullmatch(pattern, price) or Decimal(price) <= 0:
        raise ValueError('invalid_price')
    exchange = 'KRX' if market == 'KR' else body.get('exchange')
    if market == 'US' and exchange not in ('NA', 'ND', 'NY'):
        raise ValueError('invalid_exchange')
    return dict(mode=mode, market=market, side=side, code=code, quantity=quantity, price=price, exchange=exchange)


def order_request(order):
    us = order['market'] == 'US'
    api = ('ust20000' if order['side'] == 'buy' else 'ust20001') if us else ('kt10000' if order['side'] == 'buy' else 'kt10001')
    body = {'stk_cd': order['code'], 'ord_qty': order['quantity'], 'ord_uv': order['price'], 'trde_tp': '00' if us else '0'}
    body['stex_tp' if us else 'dmst_stex_tp'] = order['exchange']
    return api, '/api/us/ordr' if us else '/api/dostk/ordr', body


def connection():
    db = sqlite3.connect(DB, timeout=10)
    db.execute('CREATE TABLE IF NOT EXISTS orders (id TEXT PRIMARY KEY, created REAL, payload TEXT, status TEXT, result TEXT)')
    return db


def preview(body):
    order = normalize_order(body)
    ident = str(uuid.uuid4())
    with connection() as db:
        db.execute('INSERT INTO orders VALUES (?, ?, ?, ?, ?)', (ident, time.time(), json.dumps(order), 'preview', '{}'))
    return {'preview_id': ident, 'order': order, 'expires_in': 120, 'total': str(Decimal(order['price']) * int(order['quantity'])), 'currency': 'USD' if order['market'] == 'US' else 'KRW'}


def submit(body):
    if body.get('confirmed') is not True:
        raise ValueError('confirmation_required')
    ident = body.get('preview_id')
    if not isinstance(ident, str) or not re.fullmatch(r'[a-f0-9-]{36}', ident):
        raise ValueError('invalid_preview')
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT created,payload,status,result FROM orders WHERE id=?', (ident,)).fetchone()
        if not row:
            raise ValueError('invalid_preview')
        created, payload, status, result = row
        if status != 'preview':
            return {'status': status, **json.loads(result)}
        if time.time() - created > 120:
            raise ValueError('preview_expired')
        order = json.loads(payload)
        # Commit before the network request: timeouts/restarts must never resend.
        db.execute('UPDATE orders SET status=? WHERE id=?', ('unknown', ident))
    try:
        c = client(order['mode'])
        api, path, request = order_request(order)
        data, _ = call(c, api, path, request)
        number = str(data.get('ord_no', '')).strip()
        if not number or not number.isdigit() or int(number) == 0:
            raise RuntimeError('missing_order_number')
        status, result = 'accepted', {'order_number': number}
    except Exception:
        # Broker errors may include account details; never expose raw exceptions.
        status, result = 'unknown', {'message': '주문 결과를 확인할 수 없습니다. 키움 주문내역을 확인하고 중복 주문하지 마세요.'}
    with connection() as db:
        db.execute('UPDATE orders SET status=?,result=? WHERE id=?', (status, json.dumps(result), ident))
    return {'status': status, **result}


def route(path, body):
    if path == '/v1/trade/us/search':
        return us_search(body.get('query'))
    if path == '/v1/trade/us/quote':
        return us_quote(body.get('code'), body.get('exchange'))
    if path == '/v1/trade/preview':
        return preview(body)
    if path == '/v1/trade/submit':
        return submit(body)
    raise ValueError('invalid_route')
