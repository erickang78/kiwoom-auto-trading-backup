import sqlite3,json,unittest
from auto_performance import cumulative
class PerformanceTests(unittest.TestCase):
 def setUp(self):
  self.db=sqlite3.connect(':memory:');self.addCleanup(self.db.close);self.db.row_factory=sqlite3.Row
  self.db.execute('CREATE TABLE intents(id INTEGER PRIMARY KEY,market,strategy,status,filled,applied,average,payload)')
 def fill(self,side,price,code='A',strategy='trend',market='KR',status='filled'):
  self.db.execute('INSERT INTO intents(market,strategy,status,filled,applied,average,payload) VALUES(?,?,?,?,?,?,?)',(market,strategy,status,1,1,str(price),json.dumps(dict(side=side,code=code,exchange='KRX'))))
 def test_empty(self):
  p=cumulative(self.db,'KR','trend',[]);self.assertTrue(p['available']);self.assertIsNone(p['return_pct']);self.assertEqual(p['total_pnl'],0)
 def test_profit_and_open_position(self):
  self.fill('buy',100);self.fill('sell',110);self.fill('buy',200)
  p=cumulative(self.db,'KR','trend',[dict(exchange='KRX',code='A',strategy='trend',quantity=1,entry_price=200,last_price=190)])
  self.assertEqual(p['cumulative_buy_amount'],300);self.assertEqual(p['realized_pnl'],10);self.assertEqual(p['unrealized_pnl'],-10);self.assertEqual(p['return_pct'],0);self.assertEqual(p['win_rate_pct'],100)
 def test_scope_and_over_30_fills(self):
  for _ in range(20):self.fill('buy',100);self.fill('sell',90)
  self.fill('buy',500,strategy='breakout');self.fill('buy',500,market='US')
  p=cumulative(self.db,'KR','trend',[]);self.assertEqual(p['closed_trades'],20);self.assertEqual(p['return_pct'],-10)
 def test_invalid_ownership_or_unknown(self):
  self.fill('sell',100);self.assertFalse(cumulative(self.db,'KR','trend',[])['available'])
  self.db.execute('DELETE FROM intents');self.fill('buy',100,status='unknown');self.assertFalse(cumulative(self.db,'KR','trend',[])['available'])
if __name__=='__main__':unittest.main()
