import json
import sqlite3
import unittest
from unittest.mock import patch
from real_profit_report import build_net, build
from auto_cost_collector import record, number

class RealProfitNetTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row
        self.db.execute('CREATE TABLE intents(id INTEGER PRIMARY KEY,market,strategy,payload,status,filled,applied,average,created,updated,number)')
        self.costs=[]
    def tearDown(self):self.db.close()
    def add(self,side,qty,price,at,strategy='breakout',market='KR',fee='0',tax='0',known=True,code='SYN',status='filled'):
        p=dict(side=side,quantity=qty,exchange='KRX' if market=='KR' else 'ND',code=code)
        cur=self.db.execute('INSERT INTO intents(market,strategy,payload,status,filled,applied,average,created,updated,number) VALUES(?,?,?,?,?,?,?,?,?,?)',(market,strategy,json.dumps(p),status,qty,qty,str(price),at,at,'pending'))
        self.db.execute('UPDATE intents SET number=? WHERE id=?',(str(cur.lastrowid),cur.lastrowid))
        row=dict(self.db.execute('SELECT * FROM intents WHERE id=?',(cur.lastrowid,)).fetchone())
        if known:
            cost=record(row,p,number(fee),number(tax),'ka10076',at);cost['currency']='KRW' if market=='KR' else 'USD';self.costs.append(cost)
        return row
    def report(self,market='KR',strategy='all'):return build_net(self.db,market,strategy,self.costs)
    def test_partial_sell_period_allocation_and_exact_sums(self):
        self.add('buy',10,100,'2025-12-30T01:00:00+00:00',fee='10')
        self.add('sell',4,120,'2025-12-31T10:00:00+00:00',fee='2',tax='1')
        self.add('sell',6,90,'2026-01-03T01:00:00+00:00',fee='2',tax='1')
        r=self.report();self.assertEqual(r['summary']['pnl'],4);self.assertEqual(r['summary']['return_pct'],.4)
        self.assertEqual(r['summary']['cost'],1000);self.assertEqual(r['summary']['net_acquisition_cost'],1010)
        self.assertEqual(r['summary']['net_proceeds'],1014)
        self.assertEqual([d['pnl'] for d in r['daily']],[-69,73])
        for period in ('daily','monthly','yearly'):
            self.assertEqual(sum(x['pnl'] for x in r[period]),4);self.assertEqual(sum(x['confirmed_cost'] for x in r[period]),16)
    def test_unsold_cost_excluded(self):
        self.add('buy',10,100,'2026-01-01T01:00:00+00:00',fee='10')
        self.add('sell',4,120,'2026-01-02T01:00:00+00:00',fee='2')
        self.add('buy',1,500,'2026-01-03T01:00:00+00:00',strategy='trend',fee='100')
        r=self.report();self.assertEqual(r['summary']['confirmed_cost'],6);self.assertEqual(r['summary']['pnl'],74)
    def test_missing_buy_unique_count_across_periods(self):
        self.add('buy',10,100,'2025-12-30T01:00:00+00:00',known=False)
        self.add('sell',4,110,'2025-12-31T01:00:00+00:00')
        self.add('sell',6,110,'2026-01-03T01:00:00+00:00')
        r=self.report();self.assertEqual(r['summary']['pending_cost_orders'],1);self.assertTrue(r['provisional'])
        self.assertEqual(sum(x['pending_cost_orders'] for x in r['monthly']),2)
    def test_rebuy_strategy_and_market_isolation(self):
        self.add('buy',1,100,'2026-01-01T01:00:00+00:00',fee='1');self.add('sell',1,110,'2026-01-02T01:00:00+00:00',fee='1')
        self.add('buy',1,200,'2026-02-01T01:00:00+00:00',fee='2');self.add('sell',1,210,'2026-02-02T01:00:00+00:00',fee='2')
        self.add('buy',1,100,'2026-01-01T01:00:00+00:00',strategy='trend',fee='1');self.add('sell',1,90,'2026-01-02T01:00:00+00:00',strategy='trend',fee='1')
        self.add('buy',1,100,'2026-01-01T01:00:00+00:00',market='US',known=False);self.add('sell',1,110,'2026-01-02T01:00:00+00:00',market='US',known=False)
        self.assertEqual(self.report(strategy='breakout')['summary']['pnl'],14);self.assertEqual(self.report()['summary']['pnl'],2)
        us=self.report('US');self.assertEqual(us['currency'],'USD');self.assertEqual(us['summary']['pending_cost_orders'],2)
    def test_zero_negative_net_and_gross_preserved(self):
        self.add('buy',1,100,'2026-01-01T01:00:00+00:00',fee='1');self.add('sell',1,102,'2026-01-02T01:00:00+00:00',fee='1')
        self.assertEqual(self.report()['summary']['pnl'],0);self.assertEqual(build(self.db,'KR')['summary']['pnl'],2)
        self.costs[-1]['fee']='2';self.assertEqual(self.report()['summary']['pnl'],-1)
    def test_no_sales_no_pending_unsold_and_no_rate(self):
        self.add('buy',1,100,'2026-01-01T01:00:00+00:00',known=False)
        r=self.report();self.assertEqual(r['summary']['pending_cost_orders'],0);self.assertIsNone(r['summary']['return_pct']);self.assertEqual(r['daily'],[])
    def test_corrupt_costs_degrade_not_zero_complete(self):
        self.add('buy',1,100,'2026-01-01T01:00:00+00:00');self.add('sell',1,110,'2026-01-02T01:00:00+00:00')
        with patch('auto_performance_net.read_costs',return_value=([],'invalid cost schema')):
            r=build_net(self.db,'KR');self.assertTrue(r['available']);self.assertEqual(r['summary']['pending_cost_orders'],2);self.assertTrue(r['provisional'])
    def test_stale_duplicate_costs_not_final(self):
        self.add('buy',1,100,'2026-01-01T01:00:00+00:00');self.add('sell',1,110,'2026-01-02T01:00:00+00:00')
        self.costs[0]['filled_quantity']=2;self.costs.append(dict(self.costs[-1]))
        self.assertEqual(self.report()['summary']['pending_cost_orders'],2)
    def test_unknown_ledger_no_partial_totals(self):
        self.add('buy',1,100,'2026-01-01T01:00:00+00:00',status='unknown')
        r=self.report();self.assertFalse(r['available']);self.assertIsNone(r['summary'])
    def test_confirmation_day_timezone_unchanged(self):
        self.add('buy',1,100,'2025-12-30T01:00:00+00:00');self.add('sell',1,110,'2025-12-31T15:01:00+00:00')
        r=self.report();self.assertEqual(r['daily'][0]['period'],'2026-01-01');self.assertEqual(r['basis'],'final_fill_confirmation_date')
    def test_provisional_partial_sell_cost_count(self):
        self.add('buy',10,100,'2026-01-01T01:00:00+00:00',fee='10');self.add('sell',4,110,'2026-01-02T01:00:00+00:00',fee='2',status='partial')
        r=self.report();self.assertEqual(r['summary']['pnl'],34);self.assertEqual(r['summary']['pending_cost_orders'],1)

if __name__=='__main__':unittest.main()
