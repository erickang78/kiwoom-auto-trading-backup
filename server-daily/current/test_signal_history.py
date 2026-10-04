import datetime as dt
import json,sqlite3,unittest
from signal_history import history
class HistoryTests(unittest.TestCase):
 def setUp(self):
  self.db=sqlite3.connect(':memory:');self.addCleanup(self.db.close)
  self.db.execute('CREATE TABLE events(portfolio,data)');self.db.execute('CREATE TABLE daily_marks(portfolio,day,at,data)')
  self.now=dt.datetime(2026,9,30,12,tzinfo=dt.timezone.utc)
 def mark(self,pid,day,price=None):
  positions={} if price is None else {'KRX:A':dict(code='A',exchange='KRX',entry_price=100,last_price=price,quantity=1)}
  self.db.execute('INSERT INTO daily_marks VALUES(?,?,?,?)',(pid,day,day+'T06:00:00+00:00',json.dumps(positions)))
 def test_daily_price_and_sell_cutoff(self):
  self.mark(6,'2026-09-28',110);self.mark(6,'2026-09-29',95);self.mark(6,'2026-09-30')
  self.db.execute('INSERT INTO events VALUES(?,?)',(6,json.dumps(dict(kind='SELL',at='2026-09-30T01:00:00+00:00',entry_price=100,quantity=1,pnl=5))))
  points=history(self.db,'KR',self.now)['series'][0]['points']
  self.assertEqual([p['return_pct'] for p in points],[10,-5,5])
 def test_scope_gaps_no_trade_and_future(self):
  self.mark(6,'2026-09-27');self.mark(6,'2026-09-29',110);self.mark(6,'2026-10-01',200);self.mark(7,'2026-09-29',90);self.mark(1,'2026-09-29',120)
  kr=history(self.db,'KR',self.now);self.assertEqual(len(kr['series']),5)
  self.assertEqual([p['day'] for p in kr['series'][0]['points']],['2026-09-27','2026-09-29']);self.assertIsNone(kr['series'][0]['points'][0]['return_pct'])
  self.assertEqual(kr['series'][1]['points'][0]['return_pct'],-10);self.assertEqual(history(self.db,'US',self.now)['series'][0]['points'][0]['return_pct'],20)
 def test_invalid_mark_timestamp(self):
  self.db.execute('INSERT INTO daily_marks VALUES(?,?,?,?)',(6,'2026-09-29','','{}'));self.assertEqual(history(self.db,'KR',self.now)['series'][0]['points'],[])
if __name__=='__main__':unittest.main()
