"""Forward-only KR/US strategy paper trading. No broker order imports or calls."""
import datetime as dt
import json
import math
import sqlite3
import time
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

NY = ZoneInfo('America/New_York')
KST = ZoneInfo('Asia/Seoul')
STRATEGIES = ('trend', 'breakout', 'pullback', 'reversion', 'momentum')

def portfolio_id(market, strategy):
    if market not in ('KR', 'US') or strategy not in STRATEGIES:
        raise ValueError('invalid_signal_portfolio')
    return 1 + STRATEGIES.index(strategy) + (5 if market == 'KR' else 0)

DB = Path('/opt/kiwoom/state/signal-validation.sqlite3')
RULES = {'market': 'US', 'strategy': 'trend', 'quantity': 1, 'quantity_currency': 'KRW', 'low_price_exclusive': 10000, 'low_price_quantity': 5, 'mid_price_inclusive': 30000, 'mid_price_quantity': 2,
         'max_positions': 5, 'take_profit_pct': 5, 'stop_loss_pct': -3,
         'poll_seconds': 60, 'orders_enabled': False}


def stamp(now):
    return now.astimezone(dt.timezone.utc).isoformat()


def positive(value, signed=False):
    n = float(str(value).replace(',', ''))
    if signed:
        n = abs(n)
    if not math.isfinite(n) or n <= 0:
        raise ValueError('invalid_number')
    return n


def initial(now):
    return {'started_at': stamp(now), 'positions': {}, 'seen': {}, 'observed': {},
            'last_check': None, 'status': 'starting', 'realized_pnl': 0.0,
            'scan': {}, 'issues': []}


def regular_window(now, market='US'):
    local = now.astimezone(NY if market == 'US' else KST)
    start, end = (dt.time(9, 30), dt.time(16)) if market == 'US' else (dt.time(9), dt.time(15, 30))
    return local.weekday() < 5 and start <= local.time() < end


def buy_quantity(market, price, fx=None, rules=None):
    price = Decimal(str(price).replace(',', ''))
    rate = Decimal(str(fx).replace(',', '')) if market == 'US' else Decimal(1)
    if not price.is_finite() or price <= 0 or not rate.is_finite() or rate <= 0:
        raise ValueError('invalid_price_or_fx')
    krw = price * rate
    if rules is not None:
        return rules['low_price_quantity'] if krw < Decimal(str(rules['low_price_exclusive'])) else rules['mid_price_quantity'] if krw < Decimal(str(rules['mid_price_exclusive'])) else rules['quantity']
    return 5 if krw < Decimal('10000') else 2 if krw <= Decimal('30000') else 1


def step(state, scan, quotes, now, market='US', strategy='trend', *, valuations=None, rules=None):
    portfolio_id(market, strategy)
    """Mutate an isolated state copy; return audit events for one atomic commit.

    Reference fills use changing provider quotes, not executable prices. A volume
    increase within 180s is required; delayed quotes cannot be ruled out.
    """
    state['last_check'] = stamp(now)
    state['issues'] = []
    state['scan'] = {k: scan.get(k) for k in ('status', 'date', 'total', 'valid', 'failed')}
    state['scan']['strategy'] = strategy
    state['scan']['candidates'] = len(scan.get('stocks', [])) if scan.get('status') == 'ready' else None
    if not regular_window(now, market):
        state['status'] = 'outside_session'
        state['observed'] = {}
        return []
    state['status'] = 'monitoring'
    local = now.astimezone(NY if market == 'US' else KST)
    today = local.strftime('%Y%m%d')
    events, usable = [], {}
    for key, q in quotes.items():
        try:
            price, volume = positive(q['cur_prc'], signed=True), positive(q['acc_trde_qty'] if market == 'US' else q['trde_qty'])
            old = state['observed'].get(key)
            state['observed'][key] = {'day': today, 'volume': volume, 'at': stamp(now)}
            fresh = (old and old['day'] == today and volume > old['volume']
                     and 0 < (now - dt.datetime.fromisoformat(old['at'])).total_seconds() <= 180)
            if not fresh:
                state['issues'].append(key + ': 시세 갱신 확인 대기')
                continue
            usable[key] = (price, q)
        except (ValueError, KeyError, TypeError):
            state['issues'].append(key + ': 가격·거래량 확인 실패')
    # Always monitor existing positions even if the screener is loading or fails.
    for key, p in list(state['positions'].items()):
        if key not in usable:
            if key not in quotes:
                state['issues'].append(key + ': 시세 조회 실패')
            continue
        price, _ = usable[key]
        gain = (Decimal(str(price)) / Decimal(str(p['entry_price'])) - 1) * 100
        p.update(last_price=price, last_at=stamp(now), return_pct=float(gain))
        # Export marks before a simulated exit removes the position. Callers may
        # retain these three fields without adopting any simulated fills.
        if valuations is not None:
            valuations[key] = {field: p[field] for field in ('last_price', 'last_at', 'return_pct')}
        reason = '익절 +5%' if gain >= 5 else '손절 -3%' if gain <= -3 else None
        if reason:
            pnl = (price - p['entry_price']) * p['quantity']
            state['realized_pnl'] += pnl
            events.append(dict(p, kind='SELL', at=stamp(now), reference_price=price,
                               reason=reason, pnl=pnl))
            del state['positions'][key]
    if scan.get('status') != 'ready':
        state['issues'].append('전략 분석 대기 또는 실패 · 기존 가상 보유만 감시')
        return events
    if not scan.get('stocks'):
        state['issues'].append('전략 조건 충족 후보 0개 · 다음 분석 대기')
    try:
        signal_day = dt.datetime.strptime(scan['date'], '%Y%m%d').date()
        age = (local.date() - signal_day).days
        if not 1 <= age <= 4:
            raise ValueError('stale_signal')
    except (ValueError, KeyError, TypeError):
        state['issues'].append('신호 기준일 지연 · 신규 가상 매수 보류')
        return events
    for stock in scan.get('stocks', []):
        key = stock.get('exchange', 'KRX') + ':' + stock['code']
        signal_key = scan['date'] + ':' + key
        if key in state['positions'] or signal_key in state['seen']:
            continue
        if len(state['positions']) >= (rules or RULES)['max_positions']:
            break
        if key not in usable:
            if key not in quotes:
                state['issues'].append(key + ': 시세 조회 실패')
            continue
        price, q = usable[key]
        try:
            fx = positive(q['base_exrt']) if market == 'US' else 1.0
        except (ValueError, KeyError, TypeError):
            state['issues'].append(key + ': 환율 확인 실패')
            continue
        quantity = buy_quantity(market, price, q.get('base_exrt'), rules)
        p = dict(code=stock['code'], exchange=stock.get('exchange', 'KRX'), name=stock['name'],
                 strategy=strategy, quantity=quantity, entry_price=price, entry_fx=fx,
                 cost_krw=float(Decimal(quantity)*Decimal(str(price))*Decimal(str(fx))),
                 entry_at=stamp(now), signal_date=scan['date'], last_price=price,
                 last_at=stamp(now), return_pct=0)
        state['positions'][key] = p
        state['seen'][signal_key] = today
        events.append(dict(p, kind='BUY', at=stamp(now), reference_price=price,
                           reason=stock.get('reason', '전략 조건 충족')))
    # Retain enough deduplication history to outlive the four-day signal window.
    cutoff = (local.date() - dt.timedelta(days=30)).strftime('%Y%m%d')
    state['seen'] = {k: v for k, v in state['seen'].items() if v >= cutoff}
    state['observed'] = {k: v for k, v in state['observed'].items() if v['day'] == today}
    return events


def upgrade(data):
    value = json.loads(data)
    def rename(item):
        for old, new in (('realized_usd', 'realized_pnl'), ('entry_usd', 'entry_price'),
                         ('last_usd', 'last_price'), ('reference_usd', 'reference_price'), ('pnl_usd', 'pnl')):
            if old in item:
                item[new] = item.pop(old)
        return item
    rename(value)
    for p in value.get('positions', {}).values():
        rename(p)
    return value


def connect(path=DB):
    db = sqlite3.connect(path, timeout=5)
    db.execute('CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY, enabled INTEGER, revision INTEGER, data TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, data TEXT NOT NULL, portfolio INTEGER NOT NULL DEFAULT 1)')
    if 'portfolio' not in [r[1] for r in db.execute('PRAGMA table_info(events)')]:
        db.execute('ALTER TABLE events ADD COLUMN portfolio INTEGER NOT NULL DEFAULT 1')
    for market in ('US', 'KR'):
        for strategy in STRATEGIES:
            db.execute('INSERT OR IGNORE INTO state VALUES (?, 1, 0, ?)',
                       (portfolio_id(market, strategy), json.dumps(initial(dt.datetime.now(dt.timezone.utc)))))
    db.execute('CREATE TABLE IF NOT EXISTS daily_marks (portfolio INTEGER, day TEXT, at TEXT, data TEXT, PRIMARY KEY(portfolio, day))')
    db.commit()
    return db


def period_performance(db, pid, positions, days, now):
    if type(days) is not int or days not in (1, 3, 5, 10, 30, 50, 100):
        raise ValueError('invalid_validation_days')
    start = dt.datetime.combine(now.astimezone(KST).date() - dt.timedelta(days=days-1),
                                dt.time.min, KST)
    end = now
    closed = []
    for row in db.execute('SELECT data FROM events WHERE portfolio=?', (pid,)):
        event = upgrade(row[0])
        if event['kind'] == 'SELL' and start <= dt.datetime.fromisoformat(event['at']) <= end:
            closed.append(event)
    row = db.execute('SELECT data FROM daily_marks WHERE portfolio=? AND day<? ORDER BY day DESC LIMIT 1',
                     (pid, start.date().isoformat())).fetchone()
    baseline = json.loads(row[0]) if row else {}
    cost = realized = unrealized = 0.0
    wins = 0
    missing = False
    for is_closed, items in ((True, closed), (False, positions)):
        for p in items:
            entry = dt.datetime.fromisoformat(p['entry_at'])
            if entry > end:
                continue
            price = p['entry_price']
            if entry < start:
                mark = baseline.get(p.get('exchange', 'KRX') + ':' + p['code'])
                if not mark or mark['entry_at'] != p['entry_at']:
                    missing = True
                    continue
                price = mark['last_price']
            pnl = ((p['reference_price'] if is_closed else p['last_price']) - price) * p['quantity']
            cost += price * p['quantity']
            if is_closed:
                realized += pnl
                wins += pnl > 0
            else:
                unrealized += pnl
    result = dict(realized_pnl=realized, unrealized_pnl=unrealized, total_pnl=realized+unrealized,
                  cumulative_buy_amount=cost, return_pct=(realized+unrealized)/cost*100 if cost else None,
                  closed_trades=len(closed), win_rate_pct=wins/len(closed)*100 if closed else None)
    if missing:
        result = {k: None for k in result}
    result.update(days=days, start_at=stamp(start), end_at=stamp(end), available=not missing,
                  note='기간 시작 전 보유 종목의 평가가격 기록이 없어 수익률을 계산할 수 없습니다.' if missing else '')
    return result


def status(action='status', path=DB, market='US', strategy='trend', days=None, now=None):
    if days is not None and (type(days) is not int or days not in (1, 3, 5, 10, 30, 50, 100)):
        raise ValueError('invalid_validation_days')
    pid = portfolio_id(market, strategy)
    if action not in ('status', 'pause', 'resume'):
        raise ValueError('invalid_signal_action')
    from trading_control import status as control_status
    control = control_status(path=Path(path).with_name('trading-control.sqlite3'))
    with connect(path) as db:
        if action != 'status':
            db.execute('UPDATE state SET enabled=?, revision=revision+1 WHERE id=?', (action == 'resume', pid))
        enabled, _, data = db.execute('SELECT enabled, revision, data FROM state WHERE id=?', (pid,)).fetchone()
        result = upgrade(data)
        result.pop('observed', None)
        result.pop('seen', None)
        # Aggregate all closed trades, independently of the recent-event display limit.
        closed_cost = closed_pnl = 0.0
        wins = trades = 0
        for row in db.execute('SELECT data FROM events WHERE portfolio=?', (pid,)):
            e = upgrade(row[0])
            if e['kind'] == 'SELL':
                closed_cost += e['entry_price'] * e['quantity']
                closed_pnl += e['pnl']
                trades += 1
                wins += e['pnl'] > 0
        result['events'] = [upgrade(r[0]) for r in db.execute('SELECT data FROM events WHERE portfolio=? ORDER BY id DESC LIMIT 100', (pid,))]
        result['performance_history'] = __import__('signal_history').history(db,market,now or dt.datetime.now(dt.timezone.utc))
        period = period_performance(db, pid, list(result['positions'].values()), days, now or dt.datetime.now(dt.timezone.utc)) if days is not None else None
    positions = list(result['positions'].values())
    open_cost = sum(p['entry_price'] * p['quantity'] for p in positions)
    unrealized = sum((p['last_price'] - p['entry_price']) * p['quantity'] for p in positions)
    cost = closed_cost + open_cost
    result['performance'] = dict(realized_pnl=closed_pnl, unrealized_pnl=unrealized,
        total_pnl=closed_pnl + unrealized, cumulative_buy_amount=cost,
        return_pct=(closed_pnl + unrealized) / cost * 100 if cost else None,
        closed_trades=trades, win_rate_pct=wins / trades * 100 if trades else None,
        days=None, start_at=result['started_at'], end_at=stamp(now or dt.datetime.now(dt.timezone.utc)),
        available=True, note='최초 검증 시작부터 누적')
    if period is not None:
        result['performance'] = period
    result.update(rules=dict(RULES, market=market, strategy=strategy), enabled=bool(enabled) and control["enabled"], global_enabled=control["enabled"], orders_enabled=False,
                  market=market, strategy=strategy, currency='USD' if market == 'US' else 'KRW',
                  mode='SIGNAL_VALIDATION', positions=positions)
    return result


def cycle(path=DB, now=None, screen_fn=None, quote_fn=None, market='US', strategy='trend'):
    from trading_control import status as control_status, locked, read
    control_path = Path(path).with_name('trading-control.sqlite3')
    control = control_status(path=control_path)
    if not control['enabled']:
        return
    pid = portfolio_id(market, strategy)
    now = now or dt.datetime.now(dt.timezone.utc)
    with connect(path) as db:
        enabled, revision, data = db.execute('SELECT enabled, revision, data FROM state WHERE id=?', (pid,)).fetchone()
    if not enabled:
        return
    state = upgrade(data)
    events = []
    try:
        if screen_fn is None:
            if market == 'US':
                from us_strategy_api import screen as screen_fn
            else:
                from strategy_api import screen as screen_fn
        if quote_fn is None:
            if market == 'US':
                from price_api import us_quote as quote_fn
            else:
                from price_api import domestic_quote as quote_fn
        try:
            scan = screen_fn(strategy)
        except Exception:
            scan = {'status': 'error'}
        stocks = {p.get('exchange', 'KRX') + ':' + p['code']: p for p in state['positions'].values()}
        if scan.get('status') == 'ready':
            stocks.update({p.get('exchange', 'KRX') + ':' + p['code']: p for p in scan.get('stocks', [])})
        quotes = {}
        if regular_window(now, market):
            for key, p in stocks.items():
                try:
                    quotes[key] = (quote_fn(p['code'], p['exchange']) if market == 'US' else quote_fn(p['code']))['quote']
                except Exception:
                    pass
                time.sleep(.55)
        events = step(state, scan, quotes, now, market, strategy)
    except Exception:
        state = upgrade(data)
        events = []
        state.update(status='error', last_check=stamp(now), issues=['신호 검증 조회 실패 · 다음 주기에 재시도'])
    with locked(control_path) as gate:
        current = read(gate)
        if not current['enabled'] or current['revision'] != control['revision']:
            return
        with connect(path) as db:
            # A pause/resume during network I/O invalidates this cycle.
            changed = db.execute('UPDATE state SET data=? WHERE id=? AND enabled=1 AND revision=?',
                                 (json.dumps(state, ensure_ascii=False, allow_nan=False), pid, revision)).rowcount
            if changed:
                db.execute('INSERT OR REPLACE INTO daily_marks VALUES (?, ?, ?, ?)',
                           (pid, now.astimezone(KST).date().isoformat(), stamp(now), json.dumps(state['positions'])))
                db.executemany('INSERT INTO events(data, portfolio) VALUES (?, ?)',
                               [(json.dumps(e, ensure_ascii=False, allow_nan=False), pid) for e in events])


def worker():
    import fcntl
    with open(str(DB) + '.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        while True:
            try:
                for market in ('KR', 'US'):
                    cache = {}
                    from price_api import domestic_quote, us_quote
                    def quote(code, exchange=None):
                        key = (code, exchange)
                        if key not in cache:
                            cache[key] = us_quote(code, exchange) if exchange else domestic_quote(code)
                        return cache[key]
                    for strategy in STRATEGIES:
                        cycle(quote_fn=quote, market=market, strategy=strategy)
            except Exception:
                # Log no credentials or broker response bodies.
                print('signal_validation_cycle_failed', flush=True)
            time.sleep(RULES['poll_seconds'])


if __name__ == '__main__':
    worker()
