from signal_validation import status as signal_status
from strategy_api import screen
"""Read-only dashboard refresh API. No order endpoint is imported or exposed."""
import datetime
import json
import re
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import broker_read as broker
from credentials import load_credentials
from upbit_read import snapshot as upbit_snapshot, UpbitNotConfigured
import us_account_read
from price_api import domestic_quote, us_search, us_quote, chart
from trading_api import route as trade_route


HOST = '127.0.0.1'
PORT = 8787
REAL_BASE = 'https://api.kiwoom.com'
MOCK_BASE = 'https://mockapi.kiwoom.com'
MOCK_CREDENTIALS = Path('/opt/kiwoom/secrets/mock-credentials.json')
REAL_CREDENTIALS = Path('/opt/kiwoom/secrets/real-credentials.json')
GOLD_CREDENTIALS = Path('/opt/kiwoom/secrets/gold-credentials.json')
UPBIT_CREDENTIALS = Path('/opt/kiwoom/secrets/upbit-credentials.json')
TOKEN_PATH = Path('/opt/kiwoom/secrets/dashboard-token')
STOCK_LIST_PATH = Path('/opt/kiwoom/current/stock-list.json')
ALLOWED_ORIGIN = 'https://moa-invest-sep22.erickang78.chatgpt.site'
ALLOWED_ORIGINS = {ALLOWED_ORIGIN, 'https://example.invalid'}
LOCK = threading.Lock()
LAST_REQUEST = 0.0


def investor_flow(code):
    if not re.fullmatch(r'[0-9]{6}(?:_NX|_AL)?', code): raise ValueError('invalid_stock_code')
    client = broker.Client(REAL_BASE); client.authenticate(*load_credentials(REAL_CREDENTIALS))
    today = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).strftime('%Y%m%d')
    rows=[]; fields='dt cur_prc pre_sig pred_pre flu_rt acc_trde_qty acc_trde_prica ind_invsr frgnr_invsr orgn fnnc_invt insrnc invtrt etc_fnnc bank penfnd_etc samo_fund natn etc_corp natfor'
    for page in client.pages('ka10059', {'dt':today,'stk_cd':code,'amt_qty_tp':'1','trde_tp':'0','unit_tp':'1'}):
        data=page.get('stk_invsr_orgn')
        if not isinstance(data,list): raise broker.BrokerError('Unexpected investor-flow schema')
        rows.extend(broker.pick(row,fields) for row in data)
        if len(rows)>=60: break
    quote=list(client.pages('ka10001',{'stk_cd':code}))[0]
    return {'mode':'REAL_READ_ONLY','orders_enabled':False,'retrieved_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'stock':broker.pick(quote,'stk_cd stk_nm cur_prc flu_rt'),'unit':'백만원','rows':rows[:60]}


def public_snapshot(mode):
    real = mode == 'real'
    client = broker.Client(REAL_BASE if real else MOCK_BASE)
    client.authenticate(*load_credentials(REAL_CREDENTIALS if real else MOCK_CREDENTIALS))
    raw = broker.snapshot(client, '005930')
    us = us_account_read.snapshot(client) if real else {'positions': [], 'executions': [], 'pending_orders': []}
    broker.PATHS.update({
        'ka10075': '/api/dostk/acnt',
        'ka10076': '/api/dostk/acnt',
    })
    pending = []
    executions = []
    gold = {'connected': False, 'summary': {}, 'positions': [],
            'executions': [], 'pending_orders': []}
    if real:
        try:
            gold_client = broker.Client(REAL_BASE)
            gold_client.authenticate(*load_credentials(GOLD_CREDENTIALS))
            gold = broker.gold_snapshot(gold_client)
            gold['executions'] = []
            gold['pending_orders'] = []
            order_date = datetime.datetime.now(
                datetime.timezone(datetime.timedelta(hours=9))).strftime('%Y%m%d')
            common = {
                'ord_dt': order_date, 'qry_tp': '2', 'mrkt_deal_tp': '5',
                'stk_bond_tp': '0', 'stk_cd': '', 'fr_ord_no': '',
                'dmst_stex_tp': 'KRX',
            }
            gold_fields = (
                'ord_no orig_ord_no stk_cd stk_nm io_tp_nm trde_tp ord_qty '
                'ord_uv cntr_qty cntr_uv ord_remnq mdfy_cncl_tp data_send_end_tp ord_tm cnfm_tm'
            )
            pending_body = {
            'ord_dt': order_date, 'qry_tp': '2', 'mrkt_deal_tp': '5',
            'stk_bond_tp': '0', 'sell_tp': '0', 'stk_cd': '',
            'fr_ord_no': '', 'dmst_stex_tp': 'KRX',
            }
            for page in gold_client.pages('kt50075', pending_body):
                rows = page.get('acnt_ord_oso_prst')
                if not isinstance(rows, list):
                    raise broker.BrokerError('Unexpected gold pending-order schema')
                gold['pending_orders'].extend(
                    {**broker.pick(row, gold_fields), 'ord_dt': order_date}
                    for row in rows if int(row.get('ord_remnq') or '0') > 0
                )
            fills_body = {
            'ord_dt': order_date, 'qry_tp': '4', 'stk_bond_tp': '0',
            'sell_tp': '0', 'stk_cd': '', 'fr_ord_no': '',
            'dmst_stex_tp': 'KRX',
            }
            for page in gold_client.pages('kt50031', fills_body):
                rows = page.get('acnt_ord_cntr_prps_dtl')
                if not isinstance(rows, list):
                    raise broker.BrokerError('Unexpected gold execution schema')
                gold['executions'].extend(
                    {**broker.pick(row, gold_fields), 'ord_dt': order_date}
                    for row in rows if int(row.get('cntr_qty') or '0') > 0
                )
        except broker.BrokerError:
            # Keep the stock account usable when the customer has not opened or
            # linked a KRX gold spot account yet.
            gold['status'] = 'gold_account_unavailable'
    order_fields = (
        'ord_no stk_cd stk_nm io_tp_nm ord_stt ord_qty ord_pric '
        'cntr_qty cntr_pric oso_qty ord_dt ord_tm'
    )
    for page in client.pages('ka10075', {
        'stk_cd': '',
        'all_stk_tp': '0',
        'trde_tp': '0',
        'stex_tp': '0',
    }):
        rows = page.get('oso')
        if not isinstance(rows, list):
            raise broker.BrokerError('Unexpected pending-order schema')
        pending.extend(broker.pick(row, order_fields) for row in rows)
    for page in client.pages('ka10076', {
        'stk_cd': '',
        'qry_tp': '0',
        'sell_tp': '0',
        'ord_no': '',
        'stex_tp': '0',
    }):
        rows = page.get('cntr')
        if not isinstance(rows, list):
            raise broker.BrokerError('Unexpected execution schema')
        executions.extend(broker.pick(row, order_fields) for row in rows)
    return {
        'mode': ('REAL' if real else 'MOCK') + '_READ_ONLY',
        'orders_enabled': False,
        'retrieved_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'quote': raw['quote'],
        'cash': raw['cash'],
        'balance': raw['balance'],
        'holdings': raw['holdings'],
        'pending_orders': pending,
        'executions': executions,
        'us': us,
        'gold': gold,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = 'MoaReadOnly/1'

    def _cors(self):
        origin = self.headers.get('Origin')
        if origin in ALLOWED_ORIGINS:
            self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Vary', 'Origin')

    def _json(self, status, body):
        from trade_sources import annotate_snapshot
        body = annotate_snapshot(body)
        data = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self._cors()
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path != '/v1/market/stock-list':
            return self._json(404, {'error': 'not_found'})
        expected = TOKEN_PATH.read_text().strip()
        supplied = self.headers.get('Authorization', '').removeprefix('Bearer ')
        if not expected or not secrets.compare_digest(supplied, expected):
            return self._json(401, {'error': 'unauthorized'})
        if self.headers.get('Origin') not in ALLOWED_ORIGINS:
            return self._json(403, {'error': 'origin_not_allowed'})
        try:
            return self._json(200, json.loads(STOCK_LIST_PATH.read_text()))
        except Exception:
            return self._json(503, {'error': 'stock_list_unavailable'})

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Authorization, Content-Type')
        self.send_header('Access-Control-Max-Age', '600')
        self.end_headers()

    def do_POST(self):
        global LAST_REQUEST
        modes = {
            '/v1/real/refresh': 'real',
            '/v1/mock/refresh': 'mock',
        }
        mode = modes.get(self.path)
        is_flow = self.path == '/v1/market/investor-flow'
        is_coin = self.path == '/v1/coin/refresh'
        is_quote_domestic = self.path == '/v1/market/quote/domestic'
        is_quote_us_search = self.path == '/v1/market/quote/us/search'
        is_quote_us = self.path == '/v1/market/quote/us'
        is_chart_domestic = self.path == '/v1/market/chart/domestic'
        is_chart_us = self.path == '/v1/market/chart/us'
        is_trade = self.path in ('/v1/trade/preview', '/v1/trade/submit')
        is_strategy = self.path == '/v1/market/strategy'
        is_signal_validation = self.path == '/v1/market/signal-validation'
        is_news = self.path == '/v1/market/news'
        is_auto_trading = self.path == '/v1/trading/auto'
        is_trading_control = self.path == '/v1/trading/control'
        is_kakao = self.path == '/v1/notifications/kakao'
        is_price = is_kakao or is_auto_trading or is_trading_control or is_news or is_signal_validation or is_strategy or is_quote_domestic or is_quote_us_search or is_quote_us or is_chart_domestic or is_chart_us
        if not mode and not is_flow and not is_coin and not is_price and not is_trade:
            return self._json(404, {'error': 'not_found'})
        expected = TOKEN_PATH.read_text().strip()
        supplied = self.headers.get('Authorization', '').removeprefix('Bearer ')
        if not expected or not secrets.compare_digest(supplied, expected):
            return self._json(401, {'error': 'unauthorized'})
        if self.headers.get('Origin') not in ALLOWED_ORIGINS:
            return self._json(403, {'error': 'origin_not_allowed'})
        body = {}
        if is_flow or is_price or is_trade:
            try:
                size = min(int(self.headers.get('Content-Length', '0')), 1024)
                body = json.loads(self.rfile.read(size) or b'{}')
            except (ValueError, TypeError):
                return self._json(400, {'error': 'invalid_request'})
        if not is_price and not is_trade:
            with LOCK:
                now = time.monotonic()
                if now - LAST_REQUEST < 5:
                    return self._json(429, {'error': 'wait_before_refresh'})
                LAST_REQUEST = now
        try:
            if is_kakao:
                from kakao_notifications import control as kakao_control
                return self._json(200, kakao_control(body))
            if is_auto_trading:
                from auto_trading import control as auto_control
                action = body.get('action', 'status')
                if action != 'status':
                    print(json.dumps(dict(event='auto_control_request', action=action, confirmed=body.get('confirmed') is True, recovery_ids=body.get('confirmed_absent_orders', []), budget_type=type(body.get('budget')).__name__)), flush=True)
                try:
                    result = auto_control(body)
                except Exception as error:
                    if action != 'status':
                        print(json.dumps(dict(event='auto_control_error', action=action, error_type=type(error).__name__, reason=str(error) if str(error) in ('auto_confirmation_required','trading_paused','invalid_auto_budget','auto_strategy_has_positions','invalid_auto_portfolio','database is locked') else 'request_failed')), flush=True)
                    raise
                if action != 'status':
                    print(json.dumps(dict(event='auto_control_result', action=action, enabled=result.get('enabled'), recovery=(result.get('restart_check') or {}).get('result'))), flush=True)
                return self._json(200, result)
            if is_trading_control:
                from trading_control import status as trading_status
                return self._json(200, trading_status(body.get('action', 'status')))
            if is_signal_validation:
                return self._json(200, signal_status(str(body.get('action', 'status')), market=str(body.get('market', 'US')), strategy=str(body.get('strategy', 'trend')), days=body.get('days')))
            if is_strategy:
                return self._json(200, screen(str(body.get('strategy', 'trend')), str(body.get('market', 'KR'))))
            if is_trade:
                return self._json(200, trade_route(self.path, body))
            if is_news:
                from news_api import stock_news
                return self._json(200, stock_news(str(body.get('market', '')), str(body.get('code', '')), str(body.get('name', ''))))
            if is_quote_domestic:
                return self._json(200, domestic_quote(str(body.get('code', ''))))
            if is_chart_domestic:
                return self._json(200, chart('KR', str(body.get('code', '')), period=str(body.get('period', 'day'))))
            if is_quote_us_search:
                return self._json(200, us_search(str(body.get('query', ''))))
            if is_quote_us:
                return self._json(200, us_quote(str(body.get('code', '')).upper(), str(body.get('exchange', '')).upper()))
            if is_chart_us:
                return self._json(200, chart('US', str(body.get('code', '')).upper(), str(body.get('exchange', '')).upper(), str(body.get('period', 'day'))))
            if is_coin:
                return self._json(200, upbit_snapshot(UPBIT_CREDENTIALS))
            return self._json(200, investor_flow(str(body.get('code', ''))) if is_flow else public_snapshot(mode))
        except UpbitNotConfigured:
            return self._json(503, {'error': 'upbit_not_configured'})
        except ValueError as exc:
            return self._json(400, {'error': str(exc)})
        except Exception:
            return self._json(502, {'error': 'trade_failed' if is_trade else ('trade_failed' if is_trade else ('trade_failed' if is_trade else ('quote_failed' if is_price else ('upbit_refresh_failed' if is_coin else 'broker_refresh_failed'))))})

    def log_message(self, fmt, *args):
        return


if __name__ == '__main__':
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
