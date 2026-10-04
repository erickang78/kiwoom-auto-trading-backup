"""Read-only US stock positions and today's order fills."""
from datetime import datetime
from zoneinfo import ZoneInfo
from trading_api import call


def _pages(client, api, body):
    rows, continuation = [], None
    for _ in range(20):
        data, nxt = call(client, api, '/api/us/acnt', body, continuation)
        page_rows = data.get('result_list', [])
        if not isinstance(page_rows, list):
            raise RuntimeError('unexpected_us_account_schema')
        rows.extend(x for x in page_rows if isinstance(x, dict))
        if nxt[0] != 'Y':
            return rows
        if not nxt[1] or nxt == continuation:
            raise RuntimeError('invalid_us_account_pagination')
        continuation = nxt
    raise RuntimeError('incomplete_us_account_data')


def snapshot(client):
    positions = _pages(client, 'ust21070', {'stex_tp': '', 'stk_cd': ''})
    orders = _pages(client, 'ust21510', {'slby_tp': '0', 'stex_tp': '', 'stk_cd': ''})
    fields = ('stex_nm crnc_code stk_cd frgn_stk_nm qty poss_qty sell_alowq '
              'frgn_stk_book_uv now_pric evlt_amt pl_amt pl_rt evlt_amt_krw pl_amt_krw exch_rate').split()
    order_date = datetime.now(ZoneInfo('Asia/Seoul')).strftime('%Y-%m-%d')
    order_fields = ('ord_no orig_ord_no stex_nm crnc_code stk_cd frgn_stk_nm '
                    'slby_tp_nm ord_qty ord_uv cntr_qty cntr_uv ord_remnq ord_time '
                    'ord_resp_time ord_stat cntr_time').split()
    return {
        'positions': [{k: row.get(k, '') for k in fields} for row in positions
                      if abs(_number(row.get('poss_qty') or row.get('qty'))) > 0],
        'executions': [{**{k: row.get(k, '') for k in order_fields}, 'ord_dt': order_date} for row in orders
                       if abs(_number(row.get('cntr_qty'))) > 0],
        'pending_orders': [{**{k: row.get(k, '') for k in order_fields}, 'ord_dt': order_date} for row in orders
                           if abs(_number(row.get('ord_remnq'))) > 0],
    }


def _number(value):
    try:
        return float(str(value or '0').replace(',', ''))
    except ValueError:
        return 0
