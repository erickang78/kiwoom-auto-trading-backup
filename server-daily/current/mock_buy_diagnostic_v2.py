"""One guarded mock order that preserves Kiwoom's rejection code and message."""
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

import broker_read as broker
from credentials import load_credentials


GUARD = Path('/opt/kiwoom/data/mock-buy-diagnostic-20260923-v2.json')
BASE = 'https://mockapi.kiwoom.com'
CODE = '005930'


def order_rows(client):
    broker.PATHS.update({'ka10075': '/api/dostk/acnt', 'ka10076': '/api/dostk/acnt'})
    pending = []
    executions = []
    for api, body, field, target in [
        ('ka10075', {'stk_cd': '', 'all_stk_tp': '0', 'trde_tp': '0', 'stex_tp': '0'},
         'oso', pending),
        ('ka10076', {'stk_cd': '', 'qry_tp': '0', 'sell_tp': '0',
                     'ord_no': '', 'stex_tp': '0'}, 'cntr', executions),
    ]:
        for page in client.pages(api, body):
            rows = page.get(field)
            if not isinstance(rows, list):
                raise broker.BrokerError('Unexpected order-history schema')
            target.extend(rows)
    return pending, executions


def save(state):
    GUARD.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(GUARD, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as file:
        json.dump(state, file, ensure_ascii=False)
        file.flush()
        os.fsync(file.fileno())


def update(**values):
    state = json.loads(GUARD.read_text())
    state.update(values)
    GUARD.write_text(json.dumps(state, ensure_ascii=False))
    os.chmod(GUARD, 0o600)


def submit(client):
    body = {
        'dmst_stex_tp': 'KRX',
        'stk_cd': CODE,
        'ord_qty': '1',
        'ord_uv': '',
        'trde_tp': '3',
        'cond_uv': '',
    }
    request = urllib.request.Request(
        BASE + '/api/dostk/ordr',
        data=json.dumps(body).encode(),
        headers={
            'Content-Type': 'application/json;charset=UTF-8',
            'api-id': 'kt10000',
            'authorization': 'Bearer ' + client.token,
        },
    )
    try:
        with client.open(request, timeout=20) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        try:
            detail = json.load(exc)
        except (ValueError, OSError):
            detail = {}
        detail.setdefault('http_status', exc.code)
        return detail


def main():
    if GUARD.exists():
        print('STOPPED: diagnostic attempt already recorded')
        print(GUARD.read_text())
        return 1
    client = broker.Client()
    client.authenticate(*load_credentials())
    pending, executions = order_rows(client)
    if pending or executions:
        print('STOPPED: existing order history must be reviewed first')
        print('PENDING', len(pending), 'EXECUTIONS', len(executions))
        return 1
    quote = list(client.pages('ka10001', {'stk_cd': CODE}))[0]
    cash = list(client.pages('kt00001', {'qry_tp': '2'}))[0]
    save({
        'state': 'ATTEMPT_RESERVED',
        'environment': 'MOCK',
        'code': CODE,
        'quantity': 1,
        'order_type': 'MARKET',
        'quote_before': quote.get('cur_prc'),
        'buying_power_before': cash.get('ord_alow_amt'),
    })
    result = submit(client)
    code = str(result.get('return_code', 'MISSING'))
    message = str(result.get('return_msg', '응답 메시지 없음')).replace('\n', ' ')[:300]
    order = str(result.get('ord_no', '')).strip()
    if code != '0' or not order.strip('0 '):
        update(state='REJECTED', return_code=code, return_msg=message)
        print('ORDER_REJECTED')
        print('RETURN_CODE:', code)
        print('RETURN_MSG:', message)
        return 2
    update(state='ACCEPTED', order_number=order, return_code=code, return_msg=message)
    print('ORDER_ACCEPTED:', order)
    print('RETURN_MSG:', message)
    for _ in range(3):
        time.sleep(2)
        pending, executions = order_rows(client)
        matching_pending = [r for r in pending if str(r.get('ord_no', '')).lstrip('0') == order.lstrip('0')]
        matching_filled = [r for r in executions if str(r.get('ord_no', '')).lstrip('0') == order.lstrip('0')]
        print('MATCHING_PENDING:', len(matching_pending),
              'MATCHING_EXECUTIONS:', len(matching_filled))
        if matching_pending or matching_filled:
            break
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
