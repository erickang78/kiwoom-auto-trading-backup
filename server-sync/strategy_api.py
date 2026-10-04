"""Read-only screening of the first 100 KRX turnover-ranked instruments."""
import copy
import datetime as dt
import math
import re
import threading
import time

from price_api import _client, _call

STRATEGIES = ('trend', 'breakout', 'pullback', 'reversion', 'momentum')
_lock = threading.Lock()
_state = {'status': 'idle', 'processed': 0, 'total': 0, 'failed': 0}
_expires = 0


def number(value):
    result = abs(float(str(value).replace(',', '')))
    if not math.isfinite(result):
        raise ValueError('invalid_number')
    return result


def signals(rows):
    """Use completed daily bars; callers remove the current KST date."""
    rows = sorted(rows, key=lambda r: r['dt'])[-61:]
    if len(rows) < 61 or len({r['dt'] for r in rows}) != len(rows):
        raise ValueError('insufficient_history')
    close = [number(r['cur_prc']) for r in rows]
    high = [number(r['high_pric']) for r in rows]
    volume = [number(r['trde_qty']) for r in rows]
    if min(close) <= 0 or any(h < c for h, c in zip(high, close)) or volume[-1] <= 0:
        raise ValueError('invalid_bar')
    mean = lambda xs: sum(xs) / len(xs)
    last = close[-1]
    ma5, ma20, ma60 = (mean(close[-n:]) for n in (5, 20, 60))
    old20 = mean(close[-25:-5])
    ret5, ret20 = (100 * (last / close[-n-1] - 1) for n in (5, 20))
    high20 = max(high[-21:-1])
    volmean = mean(volume[-21:-1])
    ratio = volume[-1] / volmean if volmean > 0 else 0
    deviation = 100 * (last / ma20 - 1)
    drawdown = 100 * (last / high20 - 1)
    changes = [close[i] - close[i-1] for i in range(len(close)-14, len(close))]
    gain, loss = sum(max(x, 0) for x in changes), sum(max(-x, 0) for x in changes)
    rsi = 100 * gain / (gain + loss) if gain + loss else 50
    std = (mean([(c - ma20)**2 for c in close[-20:]]))**.5
    matches = {}
    if last > ma5 > ma20 > ma60 and ma20 > old20:
        matches['trend'] = (ret20, f'5·20·60일선 정배열 · 20일 수익률 {ret20:+.1f}%')
    if last > high20 and ratio >= 1.5:
        matches['breakout'] = (ratio, f'직전 20일 고가 돌파 · 거래량 {ratio:.1f}배')
    if ma20 > ma60 and ma20 > old20 and -3 <= deviation <= 3 and -12 <= drawdown <= -3:
        matches['pullback'] = (-abs(deviation), f'20일선 이격 {deviation:+.1f}% · 고점 대비 {drawdown:.1f}%')
    if std > 0 and last <= ma20 - 2 * std and rsi <= 35:
        matches['reversion'] = (-rsi, f'볼린저 하단 이하 · 단순 RSI(14) {rsi:.1f}')
    if ret20 >= 10 and ret5 > 0 and last > ma20:
        matches['momentum'] = (ret20, f'20일 {ret20:+.1f}% · 5일 {ret5:+.1f}%')
    return {'date': rows[-1]['dt'], 'close': last,
            'change': 100 * (last / close[-2] - 1), 'matches': matches}


def _scan():
    global _expires
    try:
        client = _client()
        data, _ = _call(client, 'ka10032', '/api/dostk/rkinfo',
                        {'mrkt_tp': '000', 'mang_stk_incls': '0', 'stex_tp': '1'})
        universe, seen = [], set()
        for row in data.get('trde_prica_upper', []):
            code = str(row.get('stk_cd', '')).removeprefix('A')
            if re.fullmatch(r'\d{6}', code) and code not in seen:
                seen.add(code)
                universe.append({'code': code, 'name': row.get('stk_nm') or code})
            if len(universe) == 100:
                break
        if not universe:
            raise RuntimeError('empty_universe')
        today = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).strftime('%Y%m%d')
        with _lock:
            _state['total'] = len(universe)
        results = []
        for stock in universe:
            time.sleep(.45)
            try:
                data, _ = _call(client, 'ka10081', '/api/dostk/chart',
                                {'stk_cd': stock['code'], 'base_dt': today, 'upd_stkpc_tp': '1'})
                bars = [r for r in data.get('stk_dt_pole_chart_qry', [])
                        if re.fullmatch(r'\d{8}', str(r.get('dt', ''))) and r['dt'] < today]
                results.append(dict(stock, **signals(bars)))
            except Exception:
                with _lock:
                    _state['failed'] += 1
            with _lock:
                _state['processed'] += 1
        if not results:
            raise RuntimeError('no_valid_bars')
        # Do not mix stale/suspended instruments with the latest available session.
        latest = max(r['date'] for r in results)
        current = [r for r in results if r['date'] == latest]
        groups = {}
        for key in STRATEGIES:
            ranked = sorted((r for r in current if key in r['matches']),
                            key=lambda r: (-r['matches'][key][0], r['code']))
            groups[key] = [{'code': r['code'], 'name': r['name'], 'close': r['close'],
                            'change': r['change'], 'reason': r['matches'][key][1]}
                           for r in ranked[:10]]
        with _lock:
            _state.update(status='ready', groups=groups, date=latest,
                          valid=len(current), stale=len(results)-len(current),
                          retrieved_at=dt.datetime.now(dt.timezone.utc).isoformat())
            _expires = time.monotonic() + 900
    except Exception:
        with _lock:
            _state.update(status='error', message='시세 분석에 실패했습니다. 잠시 후 다시 조회해 주세요.')
            _expires = time.monotonic() + 30


def screen(strategy='trend', market='KR'):
    global _state
    if market == 'US':
        from us_strategy_api import screen as us_screen
        return us_screen(strategy)
    if market != 'KR':
        raise ValueError('invalid_market')
    if strategy not in STRATEGIES:
        raise ValueError('invalid_strategy')
    with _lock:
        if _state['status'] != 'loading' and time.monotonic() >= _expires:
            _state = {'status': 'loading', 'processed': 0, 'total': 0, 'failed': 0}
            threading.Thread(target=_scan, daemon=True).start()
        result = copy.deepcopy(_state)
    groups = result.pop('groups', {})
    result.update(market='KR', currency='KRW', strategy=strategy, stocks=groups.get(strategy, []), orders_enabled=False)
    return result
