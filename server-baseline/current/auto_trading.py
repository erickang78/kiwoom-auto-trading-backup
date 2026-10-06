"""Opt-in real strategy trading. Disabled by default; broker-confirmed ownership only."""
import datetime as dt
from copy import deepcopy
import json
import re
import sqlite3
import time
from decimal import Decimal
from pathlib import Path
from signal_validation import STRATEGIES, initial, step, regular_window, stamp, positive, buy_quantity
from trading_control import locked, read
import trading_api as trade
import strategy_budget as budgets

DB = Path('/opt/kiwoom/state/auto-trading.sqlite3')
CONTROL = Path('/opt/kiwoom/state/trading-control.sqlite3')
STOCK_MARKETS = {'day': None, 'rows': {}}
REAL_RULES = dict(quantity=1, quantity_currency='KRW', low_price_exclusive=10000, low_price_quantity=10, mid_price_exclusive=30000, mid_price_quantity=4, max_positions=10, take_profit_pct=5, stop_loss_pct=-3, poll_seconds=60)


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


def connect(path=DB):
    db = sqlite3.connect(path, timeout=120, factory=ClosingConnection)
    db.row_factory = sqlite3.Row
    if [c[1] for c in db.execute('PRAGMA table_info(portfolios)') if c[5]] == ['market']:
        db.close()
        raise ValueError('legacy_schema_requires_offline_migration')
    db.execute('BEGIN IMMEDIATE')
    budgets.migrate(db)
    db.execute('CREATE TABLE IF NOT EXISTS intents (id INTEGER PRIMARY KEY, market TEXT, strategy TEXT, dedup TEXT UNIQUE, payload TEXT, status TEXT, number TEXT, filled INTEGER DEFAULT 0, average TEXT, applied INTEGER DEFAULT 0, created TEXT, updated TEXT, remaining INTEGER)')
    db.execute('CREATE TABLE IF NOT EXISTS daily_returns (market TEXT,strategy TEXT,day TEXT,at TEXT,data TEXT,PRIMARY KEY(market,strategy,day))')
    db.execute('CREATE TABLE IF NOT EXISTS intent_failures (intent_id INTEGER PRIMARY KEY, data TEXT)')
    db.commit()
    return db


def validate(market, strategy):
    if market not in ('KR', 'US') or strategy not in STRATEGIES:
        raise ValueError('invalid_auto_portfolio')


def control(body, path=DB, control_path=CONTROL):
    market, strategy = body.get('market', 'KR'), body.get('strategy', 'trend')
    validate(market, strategy)
    action = body.get('action', 'status')
    if action == 'performance':
        report_strategy = body.get('report_strategy', 'all')
        if report_strategy != 'all' and report_strategy not in STRATEGIES:
            raise ValueError('invalid_auto_portfolio')
        source = body.get('report_source', 'real')
        if source == 'virtual':
            from virtual_profit_report import read_report
            from signal_validation import DB as signal_db
            return read_report(signal_db, market, report_strategy)
        if source != 'real':
            raise ValueError('invalid_report_source')
        from real_profit_report import read_report
        return read_report(path, market, report_strategy)
    if action not in ('status', 'start', 'stop', 'check_restart', 'allocate'):
        raise ValueError('invalid_auto_action')
    with locked(control_path) as gate:
        global_state = read(gate)
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM portfolios WHERE market=? AND strategy=?', (market,strategy)).fetchone()
            state = json.loads(row['data'])
            if action == 'start':
                if body.get('confirmed') is not True:
                    raise ValueError('auto_confirmation_required')
                if not global_state['enabled']:
                    raise ValueError('trading_paused')
                budget = body.get('budget', row['budget'])
                if not isinstance(budget, str) or not budget.isdigit() or not 1 <= int(budget) <= (100000000 if market == 'KR' else 100000):
                    raise ValueError('invalid_auto_budget')
                budgets.allocate(db, market, strategy, budget)
                unresolved = db.execute("SELECT COUNT(*) FROM intents WHERE market=? AND status IN ('unknown','reconcile_error')", (market,)).fetchone()[0]
                restart_required = unresolved or (row['started'] and not row['enabled'])
                restart_ok = True
                if restart_required:
                    from auto_recovery import check
                    restart_ok = check(db,row,state,body)['result'] == 'ready'
                    if not restart_ok:
                        state.update(status='attention',issues=[state['restart_check']['message']])
                        db.execute('UPDATE portfolios SET data=? WHERE market=? AND strategy=?',(json.dumps(state),market,strategy))
                if restart_ok:
                    # Independent strategy retains its own observations, holdings and dedup.
                    if not row['enabled']:
                        state['session_started_at'] = stamp(dt.datetime.now(dt.timezone.utc))
                    state.update(status='waiting', issues=[])
                    state.pop('last_failure',None)
                    db.execute('UPDATE portfolios SET strategy=?,enabled=1,revision=revision+1,budget=?,started=?,data=? WHERE market=? AND strategy=?',
                               (strategy, budget, (row['started'] or stamp(dt.datetime.now(dt.timezone.utc))), json.dumps(state), market, strategy))
            elif action == 'allocate':
                budgets.allocate(db, market, strategy, body.get('budget'))
            elif action == 'check_restart':
                if row['enabled']:
                    raise ValueError('auto_already_running')
                from auto_recovery import check
                check(db,row,state,body)
                db.execute('UPDATE portfolios SET data=? WHERE market=? AND strategy=?',(json.dumps(state),market,strategy))
            elif action == 'stop':
                state.pop('restart_check',None)
                db.execute('UPDATE portfolios SET data=? WHERE market=? AND strategy=?',(json.dumps(state),market,strategy))
                db.execute('UPDATE portfolios SET enabled=0,revision=revision+1 WHERE market=? AND strategy=?', (market,strategy))
            row = db.execute('SELECT * FROM portfolios WHERE market=? AND strategy=?', (market,strategy)).fetchone()
            state = json.loads(row['data'])
            orders = [dict(x) for x in db.execute('SELECT * FROM intents WHERE market=? AND strategy=? ORDER BY id DESC LIMIT 30', (market,strategy))]
            profits = __import__('auto_sale_profit').sale_profits(db, market, strategy)
            for order in orders:
                order['order'] = json.loads(order.pop('payload'))
                if order['id'] in profits:
                    order['sale_profit'] = profits[order['id']]
                order['trading_source'] = 'automatic'
                order['order']['trading_source'] = 'automatic'
                order.pop('dedup', None)
                failure = db.execute('SELECT data FROM intent_failures WHERE intent_id=?', (order['id'],)).fetchone()
                if failure:
                    order['failure'] = json.loads(failure[0])
            return dict(market=market, strategy=row['strategy'], selected_strategy=strategy,
                        selected_active=row['strategy'] == strategy and bool(row['enabled']),
                        enabled=bool(row['enabled']), global_enabled=global_state['enabled'],
                        budget=row['budget'], market_budget=budgets.overview(db,market), started_at=row['started'], currency='KRW' if market == 'KR' else 'USD',
                        session_started_at=state.get('session_started_at') or ((state.get('restart_check') or {}).get('checked_at') if row['enabled'] and (state.get('restart_check') or {}).get('result') == 'ready' else None),
                        last_check=state['last_check'], status=state['status'], issues=state['issues'],
                        last_failure=state.get('last_failure'),
                        stop_reason=__import__('auto_recovery').explanation(db,row,state) if not row['enabled'] else None,
                        restart_check=state.get('restart_check'),
                        positions=list(state['positions'].values()), orders=orders,
                        performance_history=__import__('auto_performance_history').history(db,market),
                        performance=__import__('auto_performance').cumulative(db,market,strategy,list(state['positions'].values())),
                        performance_net=__import__('auto_performance_net').cumulative(db,market,strategy,list(state['positions'].values())),
                        performance_periods=__import__('auto_performance_period').periods(db,market,strategy,list(state['positions'].values())),
                        rules=dict(REAL_RULES))


def pages(c, api, path, body, key):
    result, continuation = [], None
    for _ in range(100):
        try:
            data, nxt = trade.call(c, api, path, body, continuation)
        except Exception as error:
            # Kiwoom empty-ledger response observed in authenticated read-only probes.
            # Never treat generic error 20 (e.g. invalid price) as an empty account.
            try:
                data = json.loads(str(error).split(' raw=', 1)[1])
            except (ValueError, IndexError, TypeError):
                raise error
            if (str(data.get('return_code')) == '20' and '571758:' in str(data.get('return_msg', ''))
                    and api in ('kt00018','ka10075','kt00007','ust21070','ust21050','ust21150')):
                return result
            raise error
        if str(data.get('return_code', '0')) != '0' or not isinstance(data.get(key), list):
            raise RuntimeError('account_schema')
        result.extend(data[key])
        if nxt[0] != 'Y':
            return result
        if not nxt[1] or nxt == continuation:
            raise RuntimeError('pagination')
        continuation = nxt
        time.sleep(.55)
    raise RuntimeError('incomplete_account')


def number(value):
    result = Decimal(str(value).replace(',', ''))
    if not result.is_finite() or result < 0:
        raise ValueError('invalid_account_number')
    return result


def stock_code(code, market):
    return str(code).removeprefix('A') if market == 'KR' else str(code)


def account_totals(positions, market, quantity_field, sellable_field):
    holdings, sellable = {}, {}
    for p in positions:
        code=stock_code(p['stk_cd'],market)
        quantity,available=number(p[quantity_field]),number(p[sellable_field])
        if quantity!=quantity.to_integral_value() or available!=available.to_integral_value() or available>quantity:
            raise RuntimeError('account_schema')
        holdings[code]=holdings.get(code,0)+int(quantity)
        sellable[code]=sellable.get(code,0)+int(available)
    return holdings,sellable


def account(c, market):
    if market == 'KR':
        positions = pages(c, 'kt00018', '/api/dostk/acnt', {'qry_tp':'2','dmst_stex_tp':'KRX'}, 'acnt_evlt_remn_indv_tot')
        pending = pages(c, 'ka10075', '/api/dostk/acnt', {'all_stk_tp':'0','trde_tp':'0','stk_cd':'','stex_tp':'0'}, 'oso')
        holdings,sellable=account_totals(positions,market,'rmnd_qty','trde_able_qty')
        reserved = {stock_code(p['stk_cd'], market) for p in pending if number(p['oso_qty']) > 0}
    else:
        positions = pages(c, 'ust21070', '/api/us/acnt', {'stex_tp':'','stk_cd':''}, 'result_list')
        pending = pages(c, 'ust21050', '/api/us/acnt', {'ord_dt':'','slby_tp':'0','stex_tp':'','stk_cd':''}, 'result_list')
        holdings,sellable=account_totals(positions,market,'poss_qty','sell_alowq')
        reserved = {str(p['stk_cd']) for p in pending if number(p['ord_remnq']) > 0}
    return holdings, sellable, reserved


def order_rows(c, market, date):
    if market == 'KR':
        return pages(c, 'kt00007', '/api/dostk/acnt', dict(ord_dt=date,qry_tp='1',stk_bond_tp='1',sell_tp='0',stk_cd='',fr_ord_no='',dmst_stex_tp='%'), 'acnt_ord_cntr_prps_dtl')
    return pages(c, 'ust21150', '/api/us/acnt', dict(ord_dt=date,query_tp='1',slby_tp='0',stex_tp='',stk_cd='',oppo_trde_tp='%',fr_ord_no=''), 'result_list')


def reconcile(db, c, row, state, now):
    market = row['market']
    cached = {}
    for intent in db.execute("SELECT * FROM intents WHERE market=? AND strategy=? AND status IN ('accepted','partial','unknown','reconcile_error') ORDER BY id", (market,row['strategy'])).fetchall():
        if not intent['number']:
            raise RuntimeError('unknown_order')
        date = dt.datetime.fromisoformat(intent['created']).astimezone(dt.timezone(dt.timedelta(hours=9))).strftime('%Y%m%d')
        if date not in cached:
            cached[date] = order_rows(c, market, date)
        matches = [x for x in cached[date] if str(x.get('ord_no','')).lstrip('0') == intent['number'].lstrip('0')]
        payload = json.loads(intent['payload'])
        # Ambiguous/missing broker rows are never guessed or treated as cancelled.
        if len(matches) != 1:
            raise RuntimeError('unverified_order')
        report = matches[0]
        if stock_code(report['stk_cd'], market) != payload['code']:
            raise RuntimeError('order_stock_mismatch')
        qty = int(number(report['cntr_qty']))
        remaining = int(number(report['ord_remnq']))
        average = number(report['cntr_uv']) if qty else Decimal(0)
        requested = int(payload['quantity'])
        if qty < intent['applied'] or qty > requested or (qty and average <= 0) or remaining < 0 or qty + remaining > requested:
            raise RuntimeError('order_quantity_mismatch')
        delta = qty - intent['applied']
        key = payload['exchange'] + ':' + payload['code']
        if delta:
            if payload['side'] == 'buy':
                existing = state['positions'].get(key)
                if (existing is not None and (not intent['applied'] or existing['quantity'] != intent['applied'])) or (existing is None and intent['applied']):
                    raise RuntimeError('duplicate_fill')
                state['positions'][key] = dict(code=payload['code'], exchange=payload['exchange'], name=payload['name'], strategy=intent['strategy'], quantity=qty, entry_price=float(average), entry_fx=1, cost_krw=float(average * qty), entry_at=existing['entry_at'] if existing else stamp(now), last_price=float(average), last_at=stamp(now), return_pct=0)
            else:
                if key not in state['positions'] or state['positions'][key]['quantity'] < delta:
                    raise RuntimeError('unowned_sale')
                state['positions'][key]['quantity'] -= delta
                state['positions'][key]['cost_krw'] = state['positions'][key]['entry_price'] * state['positions'][key]['quantity']
                if not state['positions'][key]['quantity']:
                    del state['positions'][key]
        status = 'filled' if qty == requested else 'cancelled' if remaining == 0 else 'partial' if qty else 'accepted'
        db.execute('UPDATE intents SET status=?,filled=?,average=?,applied=?,updated=?,remaining=? WHERE id=?',
                   (status, qty, str(average) if qty else None, qty, stamp(now), remaining, intent['id']))


def can_buy(c, order):
    quantity = int(order['quantity'])
    if order['market'] == 'KR':
        data, _ = trade.call(c, 'kt00010', '/api/dostk/acnt', dict(io_amt='0',stk_cd=order['code'],trde_tp='2',trde_qty=str(quantity),uv=order['price'],exp_buy_unp=order['price']))
        return number(data['ord_alowa']) >= number(order['price']) * quantity * Decimal('1.01') and number(data['profa_100ord_alowq']) >= quantity
    data, _ = trade.call(c, 'ust31490', '/api/us/ordr', dict(stex_tp=order['exchange'],stk_cd=order['code'],uv=order['price']))
    return number(data['ord_alowa']) >= number(order['price']) * quantity * Decimal('1.01') and number(data['min_ord_alowq']) >= quantity


def stock_market(code, c, now):
    day = now.astimezone(dt.timezone(dt.timedelta(hours=9))).date()
    if STOCK_MARKETS['day'] != day:
        STOCK_MARKETS.update(day=day, rows={})
    if code not in STOCK_MARKETS['rows']:
        data, _ = trade.call(c, 'ka10100', '/api/dostk/stkinfo', {'stk_cd':code})
        if (not isinstance(data, dict) or str(data.get('return_code')) != '0'
                or str(data.get('code')) != code):
            raise ValueError('stock_classification')
        STOCK_MARKETS['rows'][code] = str(data.get('marketCode', ''))
    return STOCK_MARKETS['rows'][code]


def kr_price_issue(code, price, now, c=None):
    # Use the broker's market classification; product-name guesses are unsafe.
    try:
        market = stock_market(code, c, now)
        if market not in ('0', '10', '8'):
            raise ValueError('stock_classification')
    except Exception:
        return '종목 분류 확인 대기 · 주문 전송 보류'
    if not price.is_finite() or price <= 0:
        return '가격 확인 실패 · 시세 재조회 대기'
    tick = 5 if market == '8' else next((unit for ceiling, unit in ((2000,1),(5000,5),
                (20000,10),(50000,50),(200000,100),(500000,500)) if price < ceiling), 1000)
    if price % tick:
        return f'가격 {price:,}원은 호가단위 {tick:,}원에 맞지 않음 · 시세 재조회 대기'
    return None


class OrderRejected(RuntimeError):
    def __init__(self, data):
        message = str(data.get('return_msg', ''))
        match = re.search(r'\b(\d{6}):', message)
        # Broker messages can include account details. Persist only safe categories/codes.
        category = next((label for word, label in (('호가','호가 오류'),('가격','가격 오류'),
                    ('수량','수량 오류'),('증거금','주문가능 금액 부족'),('잔고','잔고 확인 필요'),
                    ('시간','주문 시간 확인 필요'),('토큰','인증 확인 필요')) if word in message), '증권사 주문 거절')
        self.diagnostic = dict(stage='submit', kind='rejected', return_code=str(data['return_code']),
                               broker_code=match[1] if match else '', message=category)
        super().__init__('broker_rejected')


def rejected_response(data):
    return (isinstance(data, dict) and re.fullmatch(r'-?\d{1,8}', str(data.get('return_code', ''))) is not None
            and int(data['return_code']) != 0
            and str(data.get('ord_no', '')).strip() in ('', '0', '0000000', 'None'))


def send(c, order):
    api, path, body = trade.order_request(order)
    try:
        data, _ = trade.call(c, api, path, body)
    except Exception as error:
        # Client raises on a broker error BEFORE returning the response to this caller.
        # Only its exact API-error envelope proves an explicit rejection. HTTP failures,
        # timeouts, malformed responses and contradictory order numbers remain unknown.
        prefix = 'Kiwoom API error api_id=' + api + ' '
        if str(error).startswith(prefix):
            try:
                data = json.loads(str(error).split(' raw=', 1)[1])
            except (ValueError, IndexError, TypeError):
                raise error
            if rejected_response(data):
                raise OrderRejected(data) from None
        raise
    if rejected_response(data):
        raise OrderRejected(data)
    if not isinstance(data, dict) or str(data.get('return_code', '')) != '0':
        return 'unknown', ''
    number_ = str(data.get('ord_no', '')).strip()
    if not number_.isdigit() or int(number_) == 0:
        return 'unknown', ''
    return 'accepted', number_


def propose(state, scan, quotes, now, market, strategy):
    """Keep signal bookkeeping and validated marks, never paper ownership/P&L."""
    simulated = deepcopy(state)
    valuations = {}
    signals = step(simulated, scan, quotes, now, market, strategy, valuations=valuations, rules=REAL_RULES)
    for field in ('last_check', 'issues', 'scan', 'status', 'observed', 'seen'):
        state[field] = simulated[field]
    for key, position in state['positions'].items():
        if key in valuations:
            position.update({field: valuations[key][field]
                             for field in ('last_price', 'last_at', 'return_pct')})
    return signals


def _cycle(market, path=DB, control_path=CONTROL, now=None, client_fn=None, screen_fn=None, quote_fn=None, strategy='trend'):
    now = now or dt.datetime.now(dt.timezone.utc)
    # Lock order is always global gate -> auto DB. Stop acknowledgement waits for in-flight send.
    with locked(control_path) as gate:
        global_state = read(gate)
        if not global_state['enabled']:
            return
        with connect(path) as db:
            row = db.execute('SELECT * FROM portfolios WHERE market=? AND strategy=?', (market,strategy)).fetchone()
            if not row['enabled']:
                return
            revision = row['revision']
            market_revision=db.execute('SELECT revision FROM market_budgets WHERE market=?',(market,)).fetchone()[0]
    if not regular_window(now, market):
        with connect(path) as db:
            state = json.loads(row['data']); state.update(status='outside_session', last_check=stamp(now), observed={})
            db.execute('UPDATE portfolios SET data=? WHERE market=? AND strategy=? AND revision=?', (json.dumps(state),market,strategy,revision))
        return
    try:
        c = (client_fn or trade.client)('real')
        if screen_fn is None:
            from strategy_api import screen as kr_screen
            from us_strategy_api import screen as us_screen
            screen_fn = kr_screen if market == 'KR' else us_screen
        if quote_fn is None:
            from price_api import domestic_quote, us_quote
            quote_fn = domestic_quote if market == 'KR' else us_quote
        try:
            scan = screen_fn(row['strategy'])
        except Exception:
            scan = {'status': 'error'}
        prior = json.loads(row['data'])
        stocks = {p['exchange']+':'+p['code']:p for p in prior['positions'].values()}
        if scan.get('status') == 'ready':
            stocks.update({p.get('exchange','KRX')+':'+p['code']:p for p in scan.get('stocks',[])})
        with connect(path) as pending_db:
            for item in pending_db.execute("SELECT payload FROM intents WHERE market=? AND strategy=? AND status IN ('accepted','partial')", (market,strategy)):
                p = json.loads(item[0]); stocks[p['exchange']+':'+p['code']] = p
        quotes = {}
        for key,p in stocks.items():
            try:
                quotes[key] = (quote_fn(p['code'],p['exchange']) if market == 'US' else quote_fn(p['code']))['quote']
            except Exception:
                pass
            time.sleep(.55)
        with locked(control_path) as gate:
            current_gate = read(gate)
            if not current_gate['enabled'] or current_gate['revision'] != global_state['revision']:
                return
            with connect(path) as db:
                db.execute('BEGIN IMMEDIATE')
                current = db.execute('SELECT * FROM portfolios WHERE market=? AND strategy=?', (market,strategy)).fetchone()
                if not current['enabled'] or current['revision'] != revision:
                    return
                if db.execute('SELECT revision FROM market_budgets WHERE market=?',(market,)).fetchone()[0] != market_revision:
                    return
                state = json.loads(current['data'])
                stage = 'reconcile'
                try:
                    reconcile(db, c, current, state, now)
                    # Commit new confirmed fills to the transaction before calculating reservations.
                    db.execute('UPDATE portfolios SET data=? WHERE market=? AND strategy=?',(json.dumps(state),market,strategy))
                    stage = 'account'
                    holdings, sellable, reserved = account(c, market)
                    for key, p in state['positions'].items():
                        if holdings.get(p['code'], 0) != p['quantity']:
                            raise RuntimeError('ownership_mismatch')
                    # Signals are proposals. Ownership changes only in reconcile after verified fills.
                    signals = propose(state, scan, quotes, now, market, row['strategy'])
                    actual_positions = state['positions']
                    for failed in db.execute("SELECT i.payload,f.data FROM intents i LEFT JOIN intent_failures f ON f.intent_id=i.id WHERE i.market=? AND i.strategy=? AND i.status='failed' ORDER BY i.id DESC LIMIT 3", (market,row['strategy'])):
                        payload = json.loads(failed[0])
                        failure = json.loads(failed[1]) if failed[1] else {}
                        if failure.get('kind') == 'not_submitted_confirmed':
                            continue
                        state['issues'].append(payload['code'] + ': ' + failure.get('message','증권사 주문 거절') + ' · 실패 내역 확인 필요 (자동 재전송 없음)')
                    pending = db.execute("SELECT payload,applied,strategy FROM intents WHERE market=? AND status IN ('accepted','partial','unknown','reconcile_error')", (market,)).fetchall()
                    pending_orders = [dict(json.loads(x['payload']), applied=x['applied'], strategy=x['strategy']) for x in pending]
                    blocked = reserved | {x['code'] for x in pending_orders}
                    account_used, owned_slots = budgets.exposure(db,market)
                    own_used, own_slots = budgets.exposure(db,market,strategy)
                    used = own_used
                    market_cap = Decimal(db.execute('SELECT total_cap FROM market_budgets WHERE market=?',(market,)).fetchone()[0])
                    slots = len(set(actual_positions) | {x['exchange']+':'+x['code'] for x in pending_orders if x['side']=='buy' and x['strategy']==strategy})
                    market_unknown = db.execute("SELECT count(*) FROM intents WHERE market=? AND status IN ('unknown','reconcile_error')",(market,)).fetchone()[0]
                    stage = 'proposal'
                    for event in signals:
                        price = Decimal(str(event['reference_price']))
                        if market == 'KR':
                            issue = kr_price_issue(event['code'], price, now, c)
                            if issue:
                                state['issues'].append(event['code'] + ': ' + issue)
                                if event['kind'] == 'BUY':
                                    state['seen'].pop(event.get('signal_date','') + ':' + event['exchange'] + ':' + event['code'], None)
                                continue
                        quantity = buy_quantity(market, price, quotes.get(event['exchange']+':'+event['code'], {}).get('base_exrt'), REAL_RULES) if event['kind'] == 'BUY' else actual_positions.get(event['exchange']+':'+event['code'], {}).get('quantity', 0)
                        if quantity <= 0:
                            continue
                        order = trade.normalize_order(dict(mode='real',market=market,side=event['kind'].lower(),code=event['code'],exchange=event['exchange'],quantity=str(quantity),price=format(price.quantize(Decimal('.0001')) if market == 'US' else price.quantize(Decimal('1')),'f')))
                        order['trading_source'] = 'automatic'
                        order['name'] = event['name']
                        order['reason'] = str(event.get('reason') or '')
                        if order['code'] in blocked:
                            state['issues'].append(order['code']+': 미체결 주문 확인 대기'); continue
                        if order['side']=='buy':
                            if market_unknown:
                                state['issues'].append(order['code']+': 시장 미확인 주문 점검 대기'); continue
                            if holdings.get(order['code'],0) or order['exchange']+':'+order['code'] in owned_slots:
                                state['issues'].append(order['code']+': 기존 계좌 보유로 매수 제외'); continue
                            if slots >= REAL_RULES['max_positions'] or used+price*quantity*Decimal('1.01') > Decimal(current['budget']) or account_used+price*quantity*Decimal('1.01') > market_cap:
                                state['issues'].append(order['code']+': 예산·최대 보유 한도로 매수 제외'); continue
                            if not can_buy(c, order):
                                state['issues'].append(order['code']+': 주문가능 현금 부족'); continue
                        elif sellable.get(order['code'],0) < quantity:
                            state['issues'].append(order['code']+': 매도가능 수량 확인 대기'); continue
                        dedup = ':'.join((market,row['strategy'],order['side'],event.get('signal_date',event['entry_at']),order['exchange'],order['code']))
                        if order['side'] == 'sell':
                            dedup += ':quantity:' + str(quantity)
                        cur = db.execute("INSERT OR IGNORE INTO intents(market,strategy,dedup,payload,status,number,created,updated) VALUES (?,?,?,?, 'unknown','',?,?)", (market,row['strategy'],dedup,json.dumps(order),stamp(now),stamp(now)))
                        if not cur.rowcount:
                            continue
                        # Durable intent and state BEFORE the network call; a crash cannot resend.
                        db.execute('UPDATE portfolios SET data=? WHERE market=? AND strategy=?', (json.dumps(state),market,strategy))
                        db.commit()
                        stage = 'submit'
                        diagnostic = None
                        try:
                            status_, order_no = send(c, order)
                        except OrderRejected as error:
                            status_, order_no = 'failed', ''
                            diagnostic = error.diagnostic
                        except Exception as error:
                            status_, order_no = 'unknown', ''
                            diagnostic = dict(stage=stage, kind='unknown', error_type=type(error).__name__, message='주문 응답 확인 불가')
                        if status_ == 'unknown' and diagnostic is None:
                            diagnostic = dict(stage=stage, kind='unknown', message='주문번호 또는 응답 형식 확인 불가')
                        if diagnostic:
                            db.execute('INSERT OR REPLACE INTO intent_failures VALUES (?,?)', (cur.lastrowid,json.dumps(diagnostic)))
                            print(json.dumps(dict(event='auto_order_failure', market=market, strategy=strategy, intent_id=cur.lastrowid, **diagnostic), ensure_ascii=False), flush=True)
                        if status_ == 'failed':
                            state['issues'].append(order['code'] + ': 증권사 주문 거절 · 실패 내역 확인 필요')
                        db.execute('UPDATE intents SET status=?,number=?,updated=? WHERE id=?', (status_,order_no,stamp(now),cur.lastrowid))
                        db.commit()
                        db.execute('BEGIN IMMEDIATE')
                        blocked.add(order['code'])
                        if status_ == 'unknown':
                            raise RuntimeError('unknown_order')
                        if order['side']=='buy' and status_=='accepted':
                            used += price*quantity*Decimal('1.01'); account_used += price*quantity*Decimal('1.01'); slots += 1
                    state['status'] = 'monitoring'
                except Exception as error:
                    diagnostic = dict(stage=stage, error_type=type(error).__name__)
                    known = ('unknown_order','unverified_order','ownership_mismatch','order_stock_mismatch','order_quantity_mismatch','duplicate_fill','unowned_sale','account_schema','pagination','incomplete_account')
                    if str(error) in known:
                        diagnostic['reason'] = str(error)
                    state.pop('restart_check',None)
                    state['last_failure'] = diagnostic
                    print(json.dumps(dict(event='auto_trading_stopped',market=market,strategy=strategy,**diagnostic)),flush=True)
                    # Stop new sends on any unverified ownership/order/account state.
                    state.update(status='attention',last_check=stamp(now),issues=[f'계좌·주문 결과 확인이 필요해 자동매매를 중지했습니다. 실패 단계: {stage} · 체결·미체결 내역을 확인하세요.'])
                    db.execute('UPDATE portfolios SET enabled=0,revision=revision+1 WHERE market=? AND strategy=?',(market,strategy))
                db.execute('UPDATE portfolios SET data=? WHERE market=? AND strategy=?',(json.dumps(state,ensure_ascii=False,allow_nan=False),market,strategy))
    except Exception as error:
        print(json.dumps(dict(event='auto_trading_read_failed',market=market,strategy=strategy,error_type=type(error).__name__)),flush=True)
        with connect(path) as db:
            current=db.execute('SELECT data FROM portfolios WHERE market=? AND strategy=?',(market,strategy)).fetchone()
            state=json.loads(current[0]);state.update(status='error',last_check=stamp(now),issues=['전략·인증 조회 실패 · 주문 전송 없이 다음 주기에 재시도'])
            db.execute('UPDATE portfolios SET data=? WHERE market=? AND strategy=? AND revision=?',(json.dumps(state),market,strategy,revision))



def reconcile_stopped(market, strategy, path, control_path, now, client_fn, allow_enabled=False):
    """A stop prevents new orders, but fills of already accepted orders still belong here."""
    with locked(control_path):
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM portfolios WHERE market=? AND strategy=?',(market,strategy)).fetchone()
            if row['enabled'] and not allow_enabled:
                return
            pending=db.execute("SELECT count(*) FROM intents WHERE market=? AND strategy=? AND status IN ('accepted','partial','unknown','reconcile_error')",(market,strategy)).fetchone()[0]
            if not pending:
                return
            state=json.loads(row['data'])
            try:
                c=(client_fn or trade.client)('real')
                reconcile(db,c,row,state,now)
                holdings,_,_=account(c,market)
                if any(holdings.get(p['code'],0)!=p['quantity'] for p in state['positions'].values()):
                    raise RuntimeError('ownership_mismatch')
                state.update(status='paused' if row['enabled'] else 'stopped',last_check=stamp(now),issues=[])
            except Exception as error:
                state.update(status='attention',last_check=stamp(now),issues=['중지 전략의 기존 주문·체결 확인 필요 · 신규 주문 없음'])
                state['last_failure']=dict(stage='reconcile',error_type=type(error).__name__,reason=str(error) if str(error) in ('unknown_order','unverified_order','ownership_mismatch','duplicate_fill','unowned_sale','order_quantity_mismatch','order_stock_mismatch') else 'read_failed')
            db.execute('UPDATE portfolios SET data=? WHERE market=? AND strategy=?',(json.dumps(state),market,strategy))


def cycle(market, path=DB, control_path=CONTROL, now=None, client_fn=None, screen_fn=None, quote_fn=None, strategy=None):
    with locked(control_path) as gate:
        global_enabled=read(gate)['enabled']
    with connect(path) as db:
        choices=[(r[0],r[1]) for r in db.execute('SELECT strategy,enabled FROM portfolios WHERE market=? ORDER BY strategy',(market,))]
    if strategy is not None:
        validate(market,strategy);choices=[x for x in choices if x[0]==strategy]
    for choice,enabled in choices:
        if enabled and global_enabled:
            _cycle(market,path,control_path,now,client_fn,screen_fn,quote_fn,choice)
        else:
            reconcile_stopped(market,choice,path,control_path,now or dt.datetime.now(dt.timezone.utc),client_fn,allow_enabled=not global_enabled)

def worker():
    import fcntl
    with open(str(DB)+'.lock','w') as handle:
        fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        while True:
            for market in ('KR','US'):
                try:
                    cycle(market)
                except Exception:
                    print('auto_trading_cycle_failed',flush=True)
            time.sleep(60)

if __name__ == '__main__':
    worker()
