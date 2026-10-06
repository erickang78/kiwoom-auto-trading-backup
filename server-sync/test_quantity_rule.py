import datetime as dt
import json
import unittest
from unittest.mock import patch
from test_auto_trading import AutoTests, NOW, SCAN
import auto_trading as auto
import signal_validation as signal
from auto_performance import cumulative

class QuantityTests(AutoTests):
    def report(self,qty,remaining,price=10000):
        return [{'ord_no':'123','stk_cd':'A005930','cntr_qty':str(qty),'cntr_uv':str(price),'ord_remnq':str(remaining)}]
    def reconcile_only(self,qty,remaining,price=10000):
        with auto.connect(self.db) as db:
            row=db.execute("SELECT * FROM portfolios WHERE market='KR' AND strategy='trend'").fetchone();state=json.loads(row['data'])
            with patch.object(auto,'order_rows',return_value=self.report(qty,remaining,price)):
                auto.reconcile(db,object(),row,state,NOW)
            db.execute("UPDATE portfolios SET data=? WHERE market='KR' AND strategy='trend'",(json.dumps(state),))
    def test_threshold(self):
        for market,price,expected in [('KR',9999,5),('KR',10000,2),('KR',30000,2),('KR',30001,1),('US',5,5),('US',10,2),('US',30,2),('US',31,1)]:
            self.assertEqual(signal.buy_quantity(market,price,1000),expected)
        self.run_cycle(price=9990);self.assertEqual(self.sent[0]['quantity'],'10')
    def test_mid_price_orders_four_and_budget(self):
        self.run_cycle(price=10000);self.assertEqual(self.sent[0]['quantity'],'4')
        self.reconcile_only(4,0);self.assertEqual(self.status()['positions'][0]['quantity'],4)
        self.seed();self.run_cycle(price=10600,holdings={'005930':4});self.assertEqual(self.sent[-1]['quantity'],'4')
    def test_us_fx_quantity_and_missing_rate(self):
        now=NOW.replace(hour=14)
        cases=[('9.9999','1000',10),('10','1000',4),('30','1000',1),('30.0001','1000',1),('10','999.99',10),('10','1000.01',4),('10','3000.01',1),('10',None,None),('10','0',None),('10','NaN',None)]
        for i,(price,fx,expected) in enumerate(cases):
            path=self.db.with_name('us-'+str(i)+'.db')
            auto.control(dict(market='US',strategy='trend',action='start',confirmed=True,budget='1000'),path,self.gate)
            with auto.connect(path) as db:
                row=db.execute("SELECT data FROM portfolios WHERE market='US' AND strategy='trend'").fetchone();state=json.loads(row[0]);state['observed']={'ND:AAPL':{'day':'20260930','volume':10,'at':auto.stamp(now-dt.timedelta(seconds=60))}}
                db.execute("UPDATE portfolios SET data=? WHERE market='US' AND strategy='trend'",(json.dumps(state),))
            scan={**SCAN,'stocks':[{'code':'AAPL','exchange':'ND','name':'Apple'}]}
            with patch.object(auto,'account',return_value=({},{},set())),patch.object(auto,'can_buy',return_value=True),patch.object(auto,'send',return_value=('accepted','123')) as send:
                auto.cycle('US',path,self.gate,now,lambda mode:object(),lambda strategy:scan,lambda code,exchange:{'quote':{'cur_prc':price,'acc_trde_qty':20,'base_exrt':fx}})
                if expected is None:send.assert_not_called()
                else:self.assertEqual(send.call_args.args[1]['quantity'],str(expected))
    def test_us_cash_uses_dollar_quantity(self):
        order=dict(market='US',exchange='ND',code='AAPL',price='5',quantity='5')
        for cash,qty,expected in [(25.25,5,True),(25,5,False),(100,4,False)]:
            with patch.object(auto.trade,'call',return_value=({'ord_alowa':str(cash),'min_ord_alowq':str(qty)},None)):
                self.assertEqual(auto.can_buy(object(),order),expected)
    def test_five_share_budget(self):
        with auto.connect(self.db) as db:db.execute("UPDATE portfolios SET budget='49999' WHERE market='KR' AND strategy='trend'")
        self.run_cycle(price=9990);self.assertEqual(self.sent,[])
    def test_partial_buy_and_sell(self):
        self.run_cycle(price=9990)
        self.reconcile_only(2,3)
        p=self.status()['positions'][0];self.assertEqual(p['quantity'],2);self.assertEqual(p['cost_krw'],20000)
        self.reconcile_only(2,3);self.assertEqual(self.status()['positions'][0]['quantity'],2)
        self.reconcile_only(5,0,9990);self.assertEqual(self.status()['positions'][0]['quantity'],5)
        self.assertTrue(self.status()['performance']['available'])
        self.seed();self.run_cycle(price=10600,holdings={'005930':5})
        self.assertEqual(self.sent[-1]['side'],'sell');self.assertEqual(self.sent[-1]['quantity'],'5')
        self.reconcile_only(2,3,10600)
        self.assertEqual(self.status()['positions'][0]['quantity'],3)
        perf=self.status()['performance'];self.assertTrue(perf['available']);self.assertEqual(perf['realized_pnl'],1220);self.assertEqual(perf['closed_trades'],0)
        self.reconcile_only(5,0,10600);self.assertEqual(self.status()['positions'],[])
        perf=self.status()['performance'];self.assertEqual(perf['realized_pnl'],3050);self.assertEqual(perf['closed_trades'],1)
    def test_partial_sell_cancel_then_remaining_exit(self):
        self.run_cycle(price=9990);self.reconcile_only(5,0)
        self.seed();self.run_cycle(price=10600,holdings={'005930':5})
        self.reconcile_only(2,0,10600)
        self.seed();self.run_cycle(price=10600,holdings={'005930':3})
        self.assertEqual(len(self.sent),3);self.assertEqual(self.sent[-1]['quantity'],'3')
        self.reconcile_only(3,0,10600)
        perf=self.status()['performance'];self.assertEqual(perf['closed_trades'],1);self.assertEqual(perf['realized_pnl'],3000)
    def test_five_share_exit_requires_sellable_quantity(self):
        self.run_cycle(price=9990);self.reconcile_only(5,0);self.seed()
        with patch.object(auto,'account',return_value=({'005930':5},{'005930':4},set())),patch.object(auto,'send') as send:
            auto.cycle('KR',self.db,self.gate,NOW,lambda mode:object(),lambda strategy:SCAN,lambda code:{'quote':{'cur_prc':10600,'trde_qty':20}})
            send.assert_not_called()
    def test_partial_cancel_preserves_fill(self):
        self.run_cycle(price=9990);self.reconcile_only(2,0)
        self.assertEqual(self.status()['positions'][0]['quantity'],2);self.assertEqual(self.status()['orders'][0]['status'],'cancelled')
        self.assertTrue(self.status()['performance']['available'])
    def test_cash_and_sellable_quantity(self):
        order=dict(market='KR',code='005930',price='10000',quantity='5')
        for cash,qty,expected in [(50500,5,True),(50000,5,False),(100000,4,False)]:
            with patch.object(auto.trade,'call',return_value=({'ord_alowa':str(cash),'profa_100ord_alowq':str(qty)},None)) as call:
                self.assertEqual(auto.can_buy(object(),order),expected);self.assertEqual(call.call_args.args[3]['trde_qty'],'5')
    def test_pending_budget_counts_remaining(self):
        self.run_cycle(price=9990);self.seed()
        with auto.connect(self.db) as db:
            db.execute("UPDATE portfolios SET budget='60000' WHERE market='KR' AND strategy='trend'")
            row=db.execute("SELECT data FROM portfolios WHERE market='KR' AND strategy='trend'").fetchone();state=json.loads(row[0]);state['observed']['KRX:000001']={'day':'20260930','volume':10,'at':auto.stamp(NOW-dt.timedelta(seconds=60))};db.execute("UPDATE portfolios SET data=? WHERE market='KR' AND strategy='trend'",(json.dumps(state),))
        scan={**SCAN,'stocks':SCAN['stocks']+[{'code':'000001','name':'Other','exchange':'KRX'}]}
        self.run_cycle(price=9990,holdings={'005930':2},reports=self.report(2,8),scan=scan)
        self.assertEqual(len(self.sent),1);self.assertTrue(self.status()['enabled'])

class VirtualQuantityTests(unittest.TestCase):
    def test_new_positions_and_exit_use_five_shares(self):
        for price,expected in [(9999,5),(10000,2),(30000,2),(30001,1)]:
            state=signal.initial(NOW)
            q=lambda price,vol:{'KRX:005930':{'cur_prc':price,'trde_qty':vol}}
            signal.step(state,SCAN,q(price,10),NOW,'KR','trend')
            events=signal.step(state,SCAN,q(price,20),NOW+dt.timedelta(seconds=60),'KR','trend')
            self.assertEqual(events[0]['quantity'],expected);self.assertEqual(events[0]['cost_krw'],price*expected)
            events=signal.step(state,SCAN,q(price*1.06,30),NOW+dt.timedelta(seconds=120),'KR','trend')
            self.assertEqual(events[0]['quantity'],expected);self.assertAlmostEqual(events[0]['pnl'],price*.06*expected)

class VirtualUSTiers(unittest.TestCase):
    def test_us_fx_boundaries_and_holdings_unchanged(self):
        now=NOW.replace(hour=14);scan={**SCAN,'stocks':[{'code':'AAPL','exchange':'ND','name':'Apple'}]}
        for price,fx,expected in [('9.9999','1000',5),('10','1000',2),('30','1000',2),('30.0001','1000',1)]:
            state=signal.initial(now)
            def quote(vol,rate=fx):return {'ND:AAPL':{'cur_prc':price,'acc_trde_qty':vol,'base_exrt':rate}}
            signal.step(state,scan,quote(10),now,'US','trend')
            events=signal.step(state,scan,quote(20),now+dt.timedelta(seconds=60),'US','trend')
            self.assertEqual(events[0]['quantity'],expected)
            signal.step(state,scan,quote(30,'2000'),now+dt.timedelta(seconds=120),'US','trend')
            self.assertEqual(state['positions']['ND:AAPL']['quantity'],expected)

if __name__=='__main__':unittest.main()
