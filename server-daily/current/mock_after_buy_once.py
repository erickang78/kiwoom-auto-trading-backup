"""Submit one authorized KRX after-market MOCK order and reconcile it."""
import getpass
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

import broker_read as b
from credentials import load_credentials


GUARD = Path('/opt/kiwoom/data/samsung-after-buy.json')


def limit_price(raw):
    price = abs(int(raw))
    if not 0 < price <= 1_000_000:
        raise b.BrokerError('Unexpected quote; no order sent')
    tick = next(t for ceiling, t in [
        (2_000, 1), (5_000, 5), (20_000, 10), (50_000, 50),
        (200_000, 100), (500_000, 500), (float('inf'), 1_000)
    ] if price < ceiling)
    return price // tick * tick


def order_post(client, price):
    body = {
        'dmst_stex_tp': 'KRX',
        'stk_cd': '005930',
        'ord_qty': '1',
        'ord_uv': str(price),
        'trde_tp': '62',  # Kiwoom: 시간외단일가
        'cond_uv': '',
    }
    req = urllib.request.Request(
        b.BASE + '/api/dostk/ordr',
        data=json.dumps(body).encode(),
        headers={
            'Content-Type': 'application/json;charset=UTF-8',
            'api-id': 'kt10000',
            'authorization': 'Bearer ' + client.token,
        },
    )
    try:
        with client.open(req, timeout=20) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        raise b.BrokerError('Order HTTP ' + str(exc.code)) from None
    except (OSError, ValueError):
        raise b.BrokerError('Order response uncertain; do not retry') from None

    code = str(result.get('return_code'))
    message = str(result.get('return_msg', '')).replace('\n', ' ')[:160]
    if code != '0':
        raise b.BrokerError(f'Order rejected ({code}): {message}')
    order = result.get('ord_no')
    if not isinstance(order, str) or not order.strip('0 '):
        raise b.BrokerError('Order response uncertain; do not retry')
    return order


def reserve(price):
    fd = os.open(GUARD, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as file:
        json.dump({'state': 'ATTEMPT_RESERVED', 'market': 'KRX',
                   'trade_type': '62', 'code': '005930', 'qty': 1,
                   'limit': price}, file)
        file.flush()
        os.fsync(file.fileno())


def reconcile(client, order):
    b.PATHS.update({'ka10075': '/api/dostk/acnt', 'ka10076': '/api/dostk/acnt'})
    results = {'executions': [], 'pending': []}
    tasks = [
        ('ka10076', {'stk_cd': '005930', 'qry_tp': '1', 'sell_tp': '2',
                     'ord_no': '', 'stex_tp': '1'}, 'cntr', 'executions'),
        ('ka10075', {'stk_cd': '005930', 'all_stk_tp': '1', 'trde_tp': '2',
                     'stex_tp': '1'}, 'oso', 'pending'),
    ]
    for api, body, field, target in tasks:
        for page in client.pages(api, body):
            rows = page.get(field)
            if not isinstance(rows, list):
                raise b.BrokerError('Unexpected execution schema')
            results[target].extend(
                b.pick(row, 'ord_no ord_stt ord_qty ord_pric cntr_qty cntr_pric oso_qty')
                for row in rows
                if str(row.get('ord_no', '')).lstrip('0') == order.lstrip('0')
            )
    return results


def main():
    client = b.Client()
    client.authenticate(*load_credentials())
    if GUARD.exists():
        raise b.BrokerError('After-market attempt already recorded; no duplicate order')

    cash = list(client.pages('kt00001', {'qry_tp': '2'}))[0]
    quote = list(client.pages('ka10001', {'stk_cd': '005930'}))[0]
    price = limit_price(quote['cur_prc'])
    if int(cash['ord_alow_amt']) < price * 1.01:
        raise b.BrokerError('Insufficient mock buying power')

    print('MOCK KRX AFTER-MARKET BUY / 005930 / 1 share / LIMIT KRW', price, flush=True)
    reserve(price)
    try:
        order = order_post(client, price)
    except b.BrokerError as exc:
        saved = json.loads(GUARD.read_text())
        saved['state'] = 'REJECTED_OR_UNCERTAIN'
        saved['reason'] = str(exc)
        GUARD.write_text(json.dumps(saved))
        raise

    saved = json.loads(GUARD.read_text())
    saved.update({'state': 'ACCEPTED_NOT_YET_CONFIRMED_FILLED', 'order': order})
    GUARD.write_text(json.dumps(saved))
    print('ORDER_ACCEPTED', order, '- execution not yet confirmed', flush=True)

    for _ in range(3):
        time.sleep(3)
        status = reconcile(client, order)
        print(json.dumps(status, ensure_ascii=True), flush=True)
        if any(int(row.get('cntr_qty') or '0') >= 1 for row in status['executions']):
            print('FILL_CONFIRMED', flush=True)
            break
    else:
        print('FILL_NOT_CONFIRMED - no resubmit or price change', flush=True)

    print(json.dumps(b.snapshot(client, '005930'), ensure_ascii=True, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (b.BrokerError, FileExistsError, KeyboardInterrupt) as exc:
        print('STOPPED:', str(exc) or 'cancelled')
        print('No automatic retry. Check order state before any new attempt.')
        raise SystemExit(1)
