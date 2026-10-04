import datetime as dt
import json,sqlite3,unittest
from unittest.mock import patch
from auto_performance_period import calculate,periods,KST
class PeriodTests(unittest.TestCase):
 def setUp(self):
  self.now=dt.datetime(2026,10,1,0,30,tzinfo=dt.timezone.utc)
  self.start=dt.datetime(2026,9,29,tzinfo=KST)
  self.base=dict(available=True,holding_cost=100,unrealized_pnl=10,cumulative_buy_amount=200,realized_pnl=20,closed_trades=2,winning_trades=1)
  self.current=dict(self.base,holding_cost=100,unrealized_pnl=20,cumulative_buy_amount=250,realized_pnl=30,closed_trades=3,winning_trades=2)
 def test_opening_value_and_period_pnl(self):
  p=calculate(self.current,self.base,3,self.start,self.now)
  self.assertEqual(p['capital_base'],160);self.assertEqual(p['total_pnl'],20);self.assertEqual(p['return_pct'],12.5);self.assertEqual(p['win_rate_pct'],100)
 def test_legacy_snapshot_is_unavailable(self):
  del self.base['holding_cost'];self.assertFalse(calculate(self.current,self.base,3,self.start,self.now)['available'])
 def test_zero_capital_has_no_return(self):
  b=dict(available=True,holding_cost=0,unrealized_pnl=0,cumulative_buy_amount=0,realized_pnl=0,closed_trades=0,winning_trades=0)
  self.assertIsNone(calculate(b,b,3,self.start,self.now)['return_pct'])
 def test_inconsistent_counters_unavailable(self):
  self.current['cumulative_buy_amount']=1;self.assertFalse(calculate(self.current,self.base,3,self.start,self.now)['available'])
 def db(self):
  db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
  db.execute('CREATE TABLE intents(market,strategy,applied,created)');db.execute('CREATE TABLE daily_returns(market,strategy,day,at,data)');return db
 def test_calendar_periods_and_no_writes(self):
  db=self.db();db.execute('INSERT INTO intents VALUES(?,?,?,?)',('KR','breakout',1,'2026-09-30T00:00:00+00:00'));changes=db.total_changes
  with patch('auto_performance_period.cumulative',return_value=self.current): r=periods(db,'KR','breakout',[],self.now)
  self.assertEqual(set(r),{'3','5','10','30','50','100'});self.assertEqual(r['3']['period_start'],'2026-09-29T00:00:00+09:00');self.assertTrue(r['3']['available']);self.assertEqual(db.total_changes,changes)
 def test_missing_prior_snapshot(self):
  db=self.db();db.execute('INSERT INTO intents VALUES(?,?,?,?)',('KR','breakout',1,'2026-09-27T00:00:00+00:00'))
  with patch('auto_performance_period.cumulative',return_value=self.current): r=periods(db,'KR','breakout',[],self.now)
  self.assertFalse(r['3']['available']);self.assertTrue(r['5']['available'])
 def test_available_prior_snapshot(self):
  db=self.db();db.execute('INSERT INTO intents VALUES(?,?,?,?)',('KR','breakout',1,'2026-09-27T00:00:00+00:00'));db.execute('INSERT INTO daily_returns VALUES(?,?,?,?,?)',('KR','breakout','2026-09-28','2026-09-28T14:59:00+00:00',json.dumps(self.base)))
  with patch('auto_performance_period.cumulative',return_value=self.current): r=periods(db,'KR','breakout',[],self.now)
  self.assertEqual(r['3']['return_pct'],12.5)
if __name__=='__main__':unittest.main()
