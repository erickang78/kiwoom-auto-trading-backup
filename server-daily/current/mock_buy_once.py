"""One authorized MOCK Samsung share; no production URL or automatic retry."""
import getpass
import json
import os
import time
from pathlib import Path
import broker_read as b
from credentials import load_credentials

GUARD = Path('/opt/kiwoom/data/samsung-first-buy.json')


def limit_price(raw):
    price = abs(int(raw))
    if not 0 < price <= 1_000_000:
        raise b.BrokerError('Unexpected quote; no order sent')
    tick = next(t for ceiling, t in [(2000,1),(5000,5),(20000,10),(50000,50),
                                    (200000,100),(500000,500),(float('inf'),1000)] if price < ceiling)
    return price // tick * tick


def buy_once(c, price, guard=GUARD):
    if b.BASE != 'https://mockapi.kiwoom.com' or not c.token:
        raise b.BrokerError('MOCK authentication required')
    if price != limit_price(str(price)):
        raise b.BrokerError('Invalid limit')
    # Reserve persistently BEFORE sending. A timeout must never lead to a retry.
    fd = os.open(guard, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump({'state': 'ATTEMPT_RESERVED', 'code': '005930', 'qty': 1, 'limit': price}, f)
        f.flush()
        os.fsync(f.fileno())
    result, _ = c._post('/api/dostk/ordr', {'dmst_stex_tp': 'KRX', 'stk_cd': '005930',
        'ord_qty': '1', 'ord_uv': '', 'trde_tp': '3', 'cond_uv': ''},
        {'api-id': 'kt10000', 'authorization': 'Bearer ' + c.token})
    order = result.get('ord_no')
    if not isinstance(order, str) or not order.strip('0 '):
        raise b.BrokerError('Order response uncertain. Do not retry; reconcile first')
    with guard.open('w') as f:
        json.dump({'state': 'ACCEPTED_NOT_YET_CONFIRMED_FILLED', 'order': order,
                   'code': '005930', 'qty': 1, 'limit': price}, f)
        f.flush()
        os.fsync(f.fileno())
    return order


def reconcile(c, order):
    b.PATHS.update({'ka10075': '/api/dostk/acnt', 'ka10076': '/api/dostk/acnt'})
    filled = []
    pending = []
    for api, body, field, output in [
        ('ka10076', {'stk_cd':'005930','qry_tp':'1','sell_tp':'2','ord_no':'','stex_tp':'1'}, 'cntr', filled),
        ('ka10075', {'stk_cd':'005930','all_stk_tp':'1','trde_tp':'2','stex_tp':'1'}, 'oso', pending)]:
        for page in c.pages(api, body):
            rows = page.get(field)
            if not isinstance(rows, list):
                raise b.BrokerError('Unexpected execution schema')
            output.extend(b.pick(r, 'ord_no ord_stt ord_qty cntr_qty cntr_pric oso_qty')
                          for r in rows if str(r.get('ord_no','')).lstrip('0') == order.lstrip('0'))
    return {'executions': filled, 'pending': pending}


def main():
    c = b.Client()
    c.authenticate(*load_credentials())
    if GUARD.exists():
        saved = json.loads(GUARD.read_text())
        order = saved.get('order')
        if not order:
            raise b.BrokerError('Prior attempt uncertain. No new order; manual reconciliation required')
        print('Existing order: status check only')
    else:
        cash = list(c.pages('kt00001', {'qry_tp':'2'}))[0]
        quote = list(c.pages('ka10001', {'stk_cd':'005930'}))[0]
        price = limit_price(quote['cur_prc'])
        if int(cash['ord_alow_amt']) < price * 1.01:
            raise b.BrokerError('Insufficient mock buying power')
        print('MOCK BUY 005930 / 1 share / LIMIT KRW', price, flush=True)
        order = buy_once(c, price)
        print('ORDER_ACCEPTED', order, '- execution not confirmed', flush=True)
    for _ in range(3):
        time.sleep(3)
        status = reconcile(c, order)
        print(json.dumps(status, ensure_ascii=True), flush=True)
        if any(int(r.get('cntr_qty') or '0') >= 1 for r in status['executions']):
            print('FILL_CONFIRMED', flush=True)
            break
    else:
        print('FILL_NOT_CONFIRMED - no resubmit or price change', flush=True)
    print(json.dumps(b.snapshot(c, '005930'), ensure_ascii=True, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (Exception, KeyboardInterrupt):
        print('STOPPED. No automatic retry. If an order was attempted, check its status before doing anything else.')
        raise SystemExit(1)
