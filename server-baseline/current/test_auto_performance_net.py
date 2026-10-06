import copy
import json
from pathlib import Path
import tempfile
import unittest
import auto_performance_net as net
import auto_cost_collector as collector

DATE='20261006';STAMP='2026-10-06T01:00:00+00:00'
def intent(i=1,side='buy',qty=10,price='100',strategy='breakout',market='KR',status='filled'):
    return dict(id=i,market=market,strategy=strategy,status=status,filled=qty,applied=qty,average=price,number=str(i),created=STAMP,payload=json.dumps(dict(exchange='KRX' if market=='KR' else 'ND',code='SYN',side=side,quantity=qty)))
def cost(r,fee='10',tax='0'):
    p=json.loads(r['payload'])
    v=collector.record(r,p,collector.number(fee),collector.number(tax),'ka10076',STAMP)
    v['currency']='KRW' if r['market']=='KR' else 'USD'
    return v

def position(qty=10,last=110,market='KR',strategy='breakout'):
    return dict(exchange='KRX' if market=='KR' else 'ND',code='SYN',strategy=strategy,quantity=qty,entry_price=100,last_price=last)

class NetTests(unittest.TestCase):
    def compute(self,rows,positions,costs,market='KR',strategy='breakout'):
        return net.calculate(rows,positions,market,strategy,costs)
    def test_holding_buy_cost_only(self):
        r=intent();v=self.compute([r],[position()],[cost(r)])
        self.assertEqual(v['unrealized_pnl'],90);self.assertEqual(v['realized_pnl'],0)
        self.assertEqual(v['return_pct'],9);self.assertEqual(v['cumulative_buy_amount'],1000)
        self.assertTrue(v['coverage_complete']);self.assertFalse(v['provisional'])
    def test_partial_sells_buy_cost_allocation(self):
        b=intent();s=intent(2,'sell',4,'110');v=self.compute([b,s],[position(6)],[cost(b),cost(s,'2','1')])
        self.assertEqual((v['realized_pnl'],v['unrealized_pnl'],v['total_pnl']),(33,54,87))
    def test_closed_net_zero_is_not_win(self):
        b=intent(qty=1);s=intent(2,'sell',1,'102');v=self.compute([b,s],[],[cost(b,'1'),cost(s,'1')])
        self.assertEqual(v['return_pct'],0);self.assertEqual(v['win_rate_pct'],0)
    def test_net_negative(self):
        b=intent(qty=1);s=intent(2,'sell',1,'101');v=self.compute([b,s],[],[cost(b,'1'),cost(s,'1')])
        self.assertEqual(v['total_pnl'],-1);self.assertEqual(v['winning_trades'],0)
    def test_missing_cost_provisional(self):
        b=intent();v=self.compute([b],[position()],[])
        self.assertEqual(v['pending_cost_orders'],1);self.assertTrue(v['provisional']);self.assertFalse(v['costs_included'])
    def test_no_fills_undefined_rate(self):
        v=self.compute([],[],[]);self.assertIsNone(v['return_pct']);self.assertIsNone(v['win_rate_pct'])
    def test_stale_quantity_or_average_rejected(self):
        b=intent();r=cost(b)
        for field,value in [('filled_quantity',9),('average','101')]:
            bad={**r,field:value};self.assertEqual(self.compute([b],[position()],[bad])['pending_cost_orders'],1)
    def test_wrong_identity_side_date_currency_rejected(self):
        b=intent();r=cost(b)
        for field,value in [('intent_id',2),('side','sell'),('trade_date','20261005'),('currency','USD'),('order_number','other'),('code','OTHER'),('strategy','trend'),('market','US')]:
            self.assertEqual(self.compute([b],[position()],[{**r,field:value}])['pending_cost_orders'],1,field)
    def test_partial_snapshot_remains_pending(self):
        b=intent(status='partial');v=self.compute([b],[position()],[cost(b)])
        self.assertEqual(v['confirmed_cost_orders'],1);self.assertEqual(v['pending_cost_orders'],1)
    def test_negative_nan_cost_rejected(self):
        b=intent()
        for value in ['-1','NaN','Infinity']:
            self.assertEqual(self.compute([b],[position()],[cost(b)|{'fee':value}])['pending_cost_orders'],1)
    def test_duplicate_costs_unknown(self):
        b=intent();self.assertEqual(self.compute([b],[position()],[cost(b),cost(b)])['pending_cost_orders'],1)
    def test_strategy_manual_exclusion(self):
        b=intent();other=intent(2,strategy='trend');manual=intent(3,strategy='manual')
        v=self.compute([b,other,manual],[position()],[cost(b),cost(other,'500'),cost(manual,'900')])
        self.assertEqual(v['confirmed_fee'],10);self.assertEqual(v['filled_orders'],1)
    def test_US_currency_and_scope(self):
        b=intent(market='US');v=self.compute([b],[position(market='US')],[cost(b,'1.25')],market='US')
        self.assertEqual(v['total_pnl'],98.75)
    def test_rebuy_lots_independent(self):
        b=intent();s=intent(2,'sell',10,'110');b2=intent(3)
        v=self.compute([b,s,b2],[position()],[cost(b),cost(s,'2'),cost(b2,'3')])
        self.assertEqual(v['realized_pnl'],88);self.assertEqual(v['unrealized_pnl'],97);self.assertEqual(v['closed_trades'],1)
    def test_corrupt_and_duplicate_file(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'costs.json';p.write_text('{')
            self.assertTrue(net.read_costs(p)[1]);b=intent();p.write_text(json.dumps(dict(schema_version=1,orders=[cost(b),cost(b)])))
            self.assertTrue(net.read_costs(p)[1])
    def test_valid_json_wrong_schema_degrades_provisional(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'costs.json'
            for data in [[],None,'text',123,dict(schema_version=1,orders=[None]),dict(schema_version=1,orders=['text'])]:
                p.write_text(json.dumps(data));records,error=net.read_costs(p)
                self.assertTrue(error);b=intent();v=net.calculate([b],[position()],'KR','breakout',records,error)
                self.assertTrue(v['available']);self.assertTrue(v['provisional']);self.assertEqual(v['pending_cost_orders'],1)
    def test_unconfirmed_ledger_unavailable(self):
        b=intent(status='unknown');self.assertFalse(self.compute([b],[position()],[])['available'])

class CollectorTests(unittest.TestCase):
    def report(self,r):
        return dict(ord_no=r['number'],stk_cd='ASYN',io_tp_nm='+매수',stex_tp='1',cntr_qty=str(r['filled']),cntr_pric=r['average'],tdy_trde_cmsn='10',tdy_trde_tax='0')
    def test_exact_today(self):
        b=intent();self.assertEqual(len(collector.today_records([b],[self.report(b)],DATE,STAMP)),1)
    def test_today_duplicate_or_wrong_key_rejected(self):
        b=intent();r=self.report(b)
        self.assertFalse(collector.today_records([b],[r,r],DATE,STAMP))
        for k,v in [('io_tp_nm','-매도'),('stex_tp','2'),('cntr_qty','9'),('cntr_pric','101')]:
            self.assertFalse(collector.today_records([b],[r|{k:v}],DATE,STAMP))
    def test_missing_today_fee_not_zero(self):
        b=intent();r=self.report(b);del r['tdy_trde_tax'];self.assertFalse(collector.today_records([b],[r],DATE,STAMP))
    def test_atomic_idempotent_partial_overwrite(self):
        b=intent(qty=2,status='partial');r=cost(b,'2')
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'costs.json';self.assertEqual(collector.store(p,[r]),1)
            before=p.read_bytes();collector.store(p,[r|{'queried_at':'later'}]);self.assertEqual(p.read_bytes(),before)
            b2=intent(qty=3);r2=cost(b2,'3');collector.store(p,[r2]);saved=json.loads(p.read_text())['orders']
            self.assertEqual(len(saved),1);self.assertEqual(saved[0]['fee'],'3');self.assertEqual(p.stat().st_mode&0o777,0o600)
    def test_duplicate_existing_and_quantity_regression(self):
        r=cost(intent());self.assertRaises(ValueError,collector.merge_records,[r,r],[])
        self.assertRaises(ValueError,collector.merge_records,[r],[r|{'filled_quantity':9}])
    def past_fixture(self):
        b=intent();f=dict(_query_date=DATE,ord_no='1',cntr_no='F1',cntr_qty='10',cntr_uv='100',io_tp_nm='현금매수',dmst_stex_tp='KRX',stk_cd='ASYN')
        t=dict(cntr_dt=DATE,trde_dt='20261008',rmrk_nm='장내매수',trde_qty_jwa_cnt='10',trde_amt='1000',stex_cd='KRX',stk_cd='ASYN',orig_deal_no='000000000',cmsn='10',trde_agri_tax='0',trde_no='T1')
        return b,f,t
    def test_exact_past_execution_not_settlement_date(self):
        b,f,t=self.past_fixture();r=collector.past_records([b],[f],[],[t],[DATE],STAMP)
        self.assertEqual(len(r),1);self.assertEqual(r[0]['trade_date'],DATE)
    def test_manual_or_transaction_ambiguity_rejected(self):
        b,f,t=self.past_fixture();manual=f|{'ord_no':'2','cntr_no':'F2'}
        self.assertFalse(collector.past_records([b],[f,manual],[],[t],[DATE],STAMP))
        self.assertFalse(collector.past_records([b],[f],[],[t,t|{'trde_no':'T2'}],[DATE],STAMP))
    def test_full_partial_fill_aggregation(self):
        b,f,t=self.past_fixture();fills=[f|{'cntr_qty':'4'},f|{'cntr_no':'F2','cntr_qty':'6'}]
        self.assertEqual(len(collector.past_records([b],fills,[],[t],[DATE],STAMP)),1)
        self.assertFalse(collector.past_records([b],[fills[0]],[],[t],[DATE],STAMP))
    def test_star_symbol_requires_independent_confirmation(self):
        b,f,t=self.past_fixture();star=f|{'stk_cd':'*ASYN'}
        self.assertFalse(collector.past_records([b],[star],[],[t],[DATE],STAMP))
        confirm=f|{'cntr_uv':'100'}
        self.assertEqual(len(collector.past_records([b],[star],[confirm],[t],[DATE],STAMP)),1)
    def test_rounded_or_correction_transaction_rejected(self):
        b,f,t=self.past_fixture()
        for change in [{'trde_amt':'999'},{'orig_deal_no':'123'},{'cntr_dt':'20261005'}]:
            self.assertFalse(collector.past_records([b],[f],[],[t|change],[DATE],STAMP))

if __name__=='__main__':unittest.main()
