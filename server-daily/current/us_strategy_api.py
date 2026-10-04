"""Read-only US turnover screening using Kiwoom daily adjusted USD bars."""
import copy
import datetime as dt
import re
import threading
import time
from zoneinfo import ZoneInfo

from price_api import _client, _call
from strategy_api import STRATEGIES, signals

_lock = threading.Lock()
_state = {'status': 'idle', 'processed': 0, 'total': 0, 'failed': 0}
_expires = 0


def _today():
    return dt.datetime.now(ZoneInfo('America/New_York')).strftime('%Y%m%d')


def _universe(client):
    data, _ = _call(client, 'usa20540', '/api/us/rkinfo', {
        'stex_tp': '0', 'inds_cd': '000', 'stk_tp': '1',
        'trde_qty_tp': '0', 'stk_cnd': '0', 'pric_cnd': '0', 'trde_prica_cnd': '0'})
    stocks, seen = [], set()
    for row in data.get('result_list', []):
        code, exchange = str(row.get('stk_cd', '')), row.get('stex_tp')
        if not re.fullmatch(r'[A-Z0-9.\-/]{1,12}', code) or exchange not in ('ND', 'NY', 'NA'):
            continue
        if (code, exchange) in seen:
            continue
        seen.add((code, exchange))
        stocks.append({'code': code, 'exchange': exchange, 'name': row.get('stk_nm') or code})
        if len(stocks) == 100:
            break
    if not stocks:
        raise RuntimeError('empty_universe')
    return stocks


def _history(client, stock, today):
    data, _ = _call(client, 'usa06012', '/api/us/chart', {
        'stex_tp': stock['exchange'], 'stk_cd': stock['code'], 'strt_dt': today,
        'upd_stkpc_tp': '1', 'exrt_appl_tp': '0'})
    return [dict(row, trde_qty=row.get('acc_trde_qty', ''))
            for row in data.get('result_list', [])
            if re.fullmatch(r'\d{8}', str(row.get('dt', ''))) and row['dt'] < today]


def _scan():
    global _expires
    try:
        client = _client()
        universe, today = _universe(client), _today()
        with _lock:
            _state['total'] = len(universe)
        results = []
        for stock in universe:
            time.sleep(.55)
            try:
                results.append(dict(stock, **signals(_history(client, stock, today))))
            except Exception:
                with _lock:
                    _state['failed'] += 1
            with _lock:
                _state['processed'] += 1
        if not results:
            raise RuntimeError('no_valid_bars')
        latest = max(r['date'] for r in results)
        current = [r for r in results if r['date'] == latest]
        groups = {}
        for key in STRATEGIES:
            ranked = sorted((r for r in current if key in r['matches']),
                            key=lambda r: (-r['matches'][key][0], r['code'], r['exchange']))
            groups[key] = [dict({field: r[field] for field in ('code', 'name', 'exchange', 'close', 'change')},
                                reason=r['matches'][key][1]) for r in ranked[:10]]
        with _lock:
            _state.update(status='ready', groups=groups, date=latest, valid=len(current),
                          stale=len(results)-len(current), retrieved_at=dt.datetime.now(dt.timezone.utc).isoformat())
            _expires = time.monotonic() + 900
    except Exception:
        with _lock:
            _state.update(status='error', message='해외주식 시세 분석에 실패했습니다. 잠시 후 다시 조회해 주세요.')
            _expires = time.monotonic() + 30


def screen(strategy='trend'):
    global _state
    if strategy not in STRATEGIES:
        raise ValueError('invalid_strategy')
    with _lock:
        if _state['status'] != 'loading' and time.monotonic() >= _expires:
            _state = {'status': 'loading', 'processed': 0, 'total': 0, 'failed': 0}
            threading.Thread(target=_scan, daemon=True).start()
        result = copy.deepcopy(_state)
    groups = result.pop('groups', {})
    result.update(market='US', currency='USD', strategy=strategy, stocks=groups.get(strategy, []), orders_enabled=False)
    return result
