import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import auto_trading as auto
import trading_control as gate

NOW=dt.datetime(2026,9,30,1,10,tzinfo=dt.timezone.utc)
SCAN={'status':'ready','date':'20260929','stocks':[{'code':'005930','exchange':'KRX','name':'삼성전자','reason':'조건 충족'}]}

class AutoTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=Path(self.tmp.name)/'auto.sqlite3';self.gate=Path(self.tmp.name)/'trading-control.sqlite3'
        self.sleep=patch('auto_trading.time.sleep').start();self.addCleanup(patch.stopall);self.addCleanup(self.tmp.cleanup)
        patch.object(auto,'stock_market',return_value='10').start()
        self.start()
        self.seed()
        self.sent=[]
    def start(self,**kw):
        return auto.control(dict(market='KR',strategy='trend',action='start',confirmed=True,budget='500000',**kw),self.db,self.gate)
    def status(self):
        return auto.control({'market':'KR','strategy':'trend'},self.db,self.gate)
    def seed(self,positions=None):
        with auto.connect(self.db) as db:
            row=db.execute("SELECT data FROM portfolios WHERE market='KR'").fetchone();s=json.loads(row[0]);s['observed']={'KRX:005930':{'day':'20260930','volume':10,'at':auto.stamp(NOW-dt.timedelta(seconds=60))}}
            if positions is not None:s['positions']=positions
            db.execute("UPDATE portfolios SET data=? WHERE market='KR'",(json.dumps(s),))
    def run_cycle(self,price=70000,holdings=None,reserved=None,reports=None,send_status='accepted',scan=SCAN):
        def send(c,order):self.sent.append(order);return send_status,'000123' if send_status=='accepted' else ''
        with patch.object(auto,'account',return_value=(holdings or {},holdings or {},reserved or set())),patch.object(auto,'can_buy',return_value=True),patch.object(auto,'send',side_effect=send),patch.object(auto,'order_rows',return_value=reports or []):
            auto.cycle('KR',self.db,self.gate,NOW,lambda mode:object(),lambda strategy:scan,lambda code:{'quote':{'cur_prc':price,'trde_qty':20}})
    def test_selected_strategy_performance_does_not_change_execution(self):
        with patch('auto_performance.cumulative', return_value={'available': True, 'return_pct': 7}) as perf:
            result=auto.control({'market':'KR','strategy':'momentum','action':'status'},self.db,self.gate)
        self.assertEqual(perf.call_args.args[2],'momentum')
        self.assertEqual(result['strategy'],'trend');self.assertEqual(result['selected_strategy'],'momentum')
        self.assertTrue(result['enabled']);self.assertFalse(result['selected_active'])
        self.assertEqual(result['performance']['return_pct'],7)
        self.assertEqual(self.status()['strategy'],'trend')

    def test_disabled_default_and_confirmation(self):
        other=Path(self.tmp.name)/'fresh.db';self.assertFalse(auto.control({},other,self.gate)['enabled'])
        with self.assertRaisesRegex(ValueError,'confirmation'):auto.control({'action':'start','budget':'1'},other,self.gate)
    def test_submit_once_and_no_phantom_position(self):
        self.run_cycle();self.assertEqual(len(self.sent),1);self.assertEqual(self.status()['positions'],[])
        self.seed();self.run_cycle(reports=[{'ord_no':'123','stk_cd':'A005930','cntr_qty':'0','cntr_uv':'0','ord_remnq':'1'}]);self.assertEqual(len(self.sent),1)
    def test_verified_fill_then_sell_only_owned(self):
        self.run_cycle();self.seed()
        self.run_cycle(holdings={'005930':1},reports=[{'ord_no':'123','stk_cd':'A005930','cntr_qty':'1','cntr_uv':'70000','ord_remnq':'0'}]);self.assertEqual(len(self.status()['positions']),1)
        self.seed();self.run_cycle(price=74000,holdings={'005930':1});self.assertEqual(self.sent[-1]['side'],'sell');self.assertEqual(len(self.status()['positions']),1)
    def test_external_holding_not_bought(self):
        self.run_cycle(holdings={'005930':2});self.assertEqual(self.sent,[])
    def test_external_pending_not_bought(self):
        self.run_cycle(reserved={'005930'});self.assertEqual(self.sent,[])
    def test_budget_limit(self):
        with auto.connect(self.db) as db:db.execute("UPDATE portfolios SET budget='60000'")
        self.run_cycle();self.assertEqual(self.sent,[])
    def test_unknown_order_stops_and_cannot_restart(self):
        self.run_cycle(send_status='unknown');self.assertFalse(self.status()['enabled'])
        with patch.object(auto.trade,'client',return_value=object()),patch.object(auto,'account',return_value=({}, {}, set())):
            self.assertFalse(self.start()['enabled'])
        self.run_cycle();self.assertEqual(len(self.sent),1)
    def test_stop_preserves_intents(self):
        self.run_cycle();auto.control({'action':'stop','market':'KR'},self.db,self.gate);self.assertEqual(len(self.status()['orders']),1);self.assertFalse(self.status()['enabled'])
    def test_global_pause_and_revision(self):
        gate.status('pause',self.gate);self.run_cycle();self.assertEqual(self.sent,[])
    def test_pause_during_scan_invalidates_cycle(self):
        def scan(strategy):
            gate.status('pause',self.gate)
            with gate.locked(self.gate) as db:db.execute('UPDATE control SET enabled=1,revision=revision+1')
            return SCAN
        with patch.object(auto,'send') as send:
            auto.cycle('KR',self.db,self.gate,NOW,lambda mode:object(),scan,lambda code:{'quote':{'cur_prc':70000,'trde_qty':20}});send.assert_not_called()
    def test_missing_broker_report_stops_without_resend(self):
        self.run_cycle();self.seed();self.run_cycle();self.assertFalse(self.status()['enabled']);self.assertEqual(len(self.sent),1)
    def test_cannot_switch_active_strategy(self):
        with self.assertRaisesRegex(ValueError,'has_positions'):auto.control({'market':'KR','strategy':'breakout','action':'start','confirmed':True,'budget':'500000'},self.db,self.gate)
    def test_invalid_budget_and_market(self):
        for value in ('0','-1','1.5','100000001',True):
            with self.assertRaises(ValueError):auto.control({'market':'KR','action':'start','confirmed':True,'budget':value},self.db,self.gate)
    def test_closed_session_no_broker(self):
        with patch.object(auto.trade,'client') as client:auto.cycle('KR',self.db,self.gate,NOW.replace(hour=15));client.assert_not_called()
    def order(self):
        return dict(market='KR',side='sell',code='080220',quantity='1',price='93100',exchange='KRX')
    def test_broker_rejection_not_accepted(self):
        with patch.object(auto.trade,'call',return_value=({'return_code':20,'return_msg':'호가 오류'},('N',''))):
            with self.assertRaises(auto.OrderRejected) as caught:auto.send(object(),self.order())
        self.assertEqual(caught.exception.diagnostic['message'],'호가 오류')
    def test_client_raised_rejection_is_classified(self):
        error=RuntimeError('Kiwoom API error api_id=kt10001 return_code=20 raw=' + json.dumps({'return_code':20,'return_msg':'[2000](123456:호가 오류 계좌 1234567890)'}))
        with patch.object(auto.trade,'call',side_effect=error):
            with self.assertRaises(auto.OrderRejected) as caught:auto.send(object(),self.order())
        self.assertEqual(caught.exception.diagnostic['broker_code'],'123456')
        self.assertNotIn('1234567890',json.dumps(caught.exception.diagnostic))
    def test_ambiguous_response_remains_unknown(self):
        for data in ({'return_code':20,'ord_no':'123'}, {'ord_no':'123'}, {'return_code':0}, [], {'return_code':'timeout'}):
            with patch.object(auto.trade,'call',return_value=(data,('N',''))):
                self.assertEqual(auto.send(object(),self.order()),('unknown',''))
        for error in (TimeoutError('timeout'),RuntimeError('Kiwoom HTTP error'),RuntimeError('Kiwoom API error api_id=kt10000 raw={"return_code":20}')):
            with patch.object(auto.trade,'call',side_effect=error):
                with self.assertRaises(type(error)):auto.send(object(),self.order())
    def test_kr_tick_boundaries(self):
        from decimal import Decimal
        for price in (1999,2000,4995,5000,19990,20000,49950,50000,199900,200000,499500,500000,93100):
            self.assertIsNone(auto.kr_price_issue('080220',Decimal(price),NOW))
        for price in (2001,4999,5001,19999,20001,49999,50001,199999,200001,499999,500001,93150):
            self.assertIn('호가단위',auto.kr_price_issue('080220',Decimal(price),NOW))
    def test_unknown_product_and_classification_failure_fail_closed(self):
        from decimal import Decimal
        with patch.object(auto,'stock_market',return_value='50'):
            self.assertIn('종목 분류',auto.kr_price_issue('999999',Decimal(93150),NOW))
        with patch.object(auto,'stock_market',side_effect=TimeoutError()):
            self.assertIn('종목 분류',auto.kr_price_issue('080220',Decimal(93100),NOW))
    def test_etf_uses_own_tick(self):
        from decimal import Decimal
        with patch.object(auto,'stock_market',return_value='8'):
            self.assertIsNone(auto.kr_price_issue('069500',Decimal(93150),NOW))
            self.assertIn('호가단위 5원',auto.kr_price_issue('069500',Decimal(93151),NOW))
    def test_invalid_quote_is_not_sent_and_buy_can_retry(self):
        self.run_cycle(price=93150)
        self.assertEqual(self.sent,[]);self.assertTrue(self.status()['enabled'])
        self.assertIn('호가단위',str(self.status()['issues']))
        self.seed();self.run_cycle(price=93100)
        self.assertEqual(len(self.sent),1)
    def test_invalid_sell_quote_preserves_position_and_retries_valid_quote(self):
        position=dict(code='080220',exchange='KRX',name='제주반도체',strategy='trend',quantity=1,entry_price=88400,entry_fx=1,cost_krw=88400,entry_at=auto.stamp(NOW),last_price=88400,last_at=auto.stamp(NOW),return_pct=0)
        self.seed({'KRX:080220':position})
        with auto.connect(self.db) as db:
            state=json.loads(db.execute("SELECT data FROM portfolios WHERE market='KR'").fetchone()[0])
            state['observed']['KRX:080220']=state['observed']['KRX:005930']
            db.execute("UPDATE portfolios SET data=? WHERE market='KR'",(json.dumps(state),))
        self.run_cycle(price=93150,holdings={'080220':1},scan={'status':'error'})
        self.assertEqual(self.sent,[]);self.assertTrue(self.status()['enabled'])
        self.assertEqual(self.status()['positions'][0]['quantity'],1)
        with patch.object(auto,'account',return_value=({'080220':1},{'080220':1},set())),patch.object(auto,'send',return_value=('accepted','124')) as send:
            auto.cycle('KR',self.db,self.gate,NOW+dt.timedelta(seconds=60),lambda mode:object(),lambda strategy:{'status':'error'},lambda code:{'quote':{'cur_prc':93200,'trde_qty':30}})
            self.assertEqual(send.call_args.args[1]['side'],'sell')
            self.assertEqual(send.call_args.args[1]['price'],'93200')
    def test_rejected_order_does_not_stop_and_is_recorded_without_retry(self):
        with patch.object(auto,'account',return_value=({}, {}, set())),patch.object(auto,'can_buy',return_value=True),patch.object(auto.trade,'call',side_effect=RuntimeError('Kiwoom API error api_id=kt10000 raw={"return_code":20,"return_msg":"호가 오류"}')) as call:
            for _ in range(2):
                self.seed()
                auto.cycle('KR',self.db,self.gate,NOW,lambda mode:object(),lambda strategy:SCAN,lambda code:{'quote':{'cur_prc':70000,'trde_qty':20}})
            self.assertEqual(call.call_count,1)
        status=self.status();self.assertTrue(status['enabled'])
        self.assertEqual(status['orders'][0]['status'],'failed')
        self.assertEqual(status['orders'][0]['failure']['return_code'],'20')
    def test_timeout_stops_and_diagnostic_survives(self):
        with patch.object(auto,'account',return_value=({}, {}, set())),patch.object(auto,'can_buy',return_value=True),patch.object(auto.trade,'call',side_effect=TimeoutError('secret account details')):
            auto.cycle('KR',self.db,self.gate,NOW,lambda mode:object(),lambda strategy:SCAN,lambda code:{'quote':{'cur_prc':70000,'trde_qty':20}})
        status=self.status();self.assertFalse(status['enabled'])
        self.assertEqual(status['last_failure']['stage'],'submit')
        self.assertEqual(status['orders'][0]['failure']['error_type'],'TimeoutError')
        self.assertNotIn('secret',json.dumps(status))
        with patch.object(auto.trade,'client',return_value=object()),patch.object(auto,'account',return_value=({}, {}, set())):
            self.assertFalse(self.start()['enabled'])
    def test_empty_ledger_response_only_specific_code(self):
        error = RuntimeError('Kiwoom API error return_code=20 raw=' + json.dumps({'return_code':20,'return_msg':'[2000](571758:조회 자료가 존재하지 않습니다.)'}))
        with patch.object(auto.trade,'call',side_effect=error):
            self.assertEqual(auto.pages(object(),'ust21050','/api/us/acnt',{},'result_list'),[])
            with self.assertRaises(RuntimeError):auto.pages(object(),'ust20000','/api/us/ordr',{},'result_list')
        error = RuntimeError('Kiwoom API error return_code=20 raw=' + json.dumps({'return_code':20,'return_msg':'invalid price'}))
        with patch.object(auto.trade,'call',side_effect=error):
            with self.assertRaises(RuntimeError):auto.pages(object(),'ust21050','/api/us/acnt',{},'result_list')
    def test_screen_failure_still_monitors_owned(self):
        self.run_cycle();self.seed()
        self.run_cycle(holdings={'005930':1},reports=[{'ord_no':'123','stk_cd':'A005930','cntr_qty':'1','cntr_uv':'70000','ord_remnq':'0'}]);self.seed()
        def bad(strategy):raise RuntimeError('analysis')
        with patch.object(auto,'account',return_value=({'005930':1},{'005930':1},set())),patch.object(auto,'send',return_value=('accepted','124')) as send:
            auto.cycle('KR',self.db,self.gate,NOW,lambda mode:object(),bad,lambda code:{'quote':{'cur_prc':74000,'trde_qty':20}})
            self.assertEqual(send.call_args.args[1]['side'],'sell')
    def test_us_request_and_cash(self):
        order=dict(mode='real',market='US',side='buy',code='AAPL',quantity='1',price='200.0000',exchange='ND')
        with patch.object(auto.trade,'call',return_value=({'ord_alowa':'1000','min_ord_alowq':'5'},('N',''))) as call:
            self.assertTrue(auto.can_buy(object(),order));self.assertEqual(call.call_args.args[1],'ust31490')

if __name__=='__main__':unittest.main()
