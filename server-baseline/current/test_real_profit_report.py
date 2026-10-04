import json,sqlite3,unittest
from real_profit_report import build
class ReportTests(unittest.TestCase):
 def setUp(self):
  self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row
  self.db.execute('CREATE TABLE intents(id INTEGER PRIMARY KEY,market,strategy,payload,status,filled,applied,average,updated)')
 def add(self,side,qty,price,at,strategy='breakout',market='KR',status='filled',code='000001'):
  self.db.execute('INSERT INTO intents(market,strategy,payload,status,filled,applied,average,updated) VALUES(?,?,?,?,?,?,?,?)',(market,strategy,json.dumps(dict(side=side,quantity=qty,exchange='KRX',code=code)),status,qty,qty,str(price),at))
 def test_partial_sales_weighted_month_and_timezone(self):
  self.add('buy',10,100,'2025-12-30T01:00:00+00:00')
  self.add('sell',4,120,'2025-12-31T15:01:00+00:00')
  self.add('sell',6,90,'2026-01-03T01:00:00+00:00')
  r=build(self.db,'KR');self.assertEqual(r['summary']['pnl'],20);self.assertEqual(r['summary']['return_pct'],2)
  self.assertEqual(r['monthly'][0]['period'],'2026-01');self.assertEqual(len(r['yearly']),1);self.assertEqual(r['daily'][1]['period'],'2026-01-01')
 def test_market_strategy_and_open_positions(self):
  self.add('buy',1,100,'2026-01-01T00:00:00+00:00');self.add('sell',1,110,'2026-01-02T00:00:00+00:00')
  self.add('buy',1,999,'2026-01-03T00:00:00+00:00',strategy='trend')
  self.add('buy',1,10,'2026-01-01T00:00:00+00:00',market='US');self.add('sell',1,8,'2026-01-02T00:00:00+00:00',market='US')
  self.assertEqual(build(self.db,'KR')['summary']['pnl'],10);self.assertEqual(build(self.db,'US')['summary']['pnl'],-2)
  self.assertEqual(build(self.db,'KR','trend')['daily'],[])
 def test_unverified_or_missing_basis_not_zero_profit(self):
  self.add('sell',1,110,'2026-01-02T00:00:00+00:00');r=build(self.db,'KR');self.assertFalse(r['available']);self.assertIsNone(r['summary'])
 def test_empty(self):
  r=build(self.db,'KR');self.assertTrue(r['available']);self.assertIsNone(r['summary']['return_pct']);self.assertEqual(r['daily'],[])
if __name__=='__main__':unittest.main()
