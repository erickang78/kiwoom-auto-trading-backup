import datetime as dt
import json,tempfile,unittest
from pathlib import Path
import auto_trading as auto
import auto_performance_history as h
class RealHistoryTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.path=Path(self.tmp.name)/'auto.db'
  with auto.connect(self.path):pass
  self.now=dt.datetime(2026,9,30,1,tzinfo=dt.timezone.utc)
 def test_empty_snapshot_does_not_change_trading(self):
  with auto.connect(self.path) as db:
   before=[tuple(r) for r in db.execute('SELECT * FROM portfolios')]
  h.snapshot(self.path,self.now)
  with auto.connect(self.path) as db:
   self.assertEqual([tuple(r) for r in db.execute('SELECT * FROM portfolios')],before)
   self.assertEqual(db.execute('SELECT COUNT(*) FROM intents').fetchone()[0],0)
   self.assertEqual(db.execute('SELECT COUNT(*) FROM daily_returns').fetchone()[0],10)
   self.assertIsNone(h.history(db,'KR')['series'][0]['points'][0]['return_pct'])
 def test_prices_days_and_strategy_isolation(self):
  with auto.connect(self.path) as db:
   payload=json.dumps(dict(side='buy',code='A',exchange='KRX'))
   db.execute('INSERT INTO intents(market,strategy,dedup,payload,status,filled,applied,average) VALUES(?,?,?,?,?,?,?,?)',('KR','trend','buy1',payload,'filled',1,1,'100'))
   row=db.execute("SELECT data FROM portfolios WHERE market='KR'").fetchone();state=json.loads(row[0]);state['positions']={'KRX:A':dict(code='A',exchange='KRX',strategy='trend',quantity=1,entry_price=100,last_price=110)}
   db.execute("UPDATE portfolios SET data=? WHERE market='KR'",(json.dumps(state),))
  h.snapshot(self.path,self.now)
  with auto.connect(self.path) as db:
   state['positions']['KRX:A']['last_price']=95;db.execute("UPDATE portfolios SET data=? WHERE market='KR'",(json.dumps(state),))
  h.snapshot(self.path,self.now+dt.timedelta(days=1))
  with auto.connect(self.path) as db:
   series=h.history(db,'KR')['series'];self.assertEqual([p['return_pct'] for p in series[0]['points']],[10,-5]);self.assertIsNone(series[1]['points'][0]['return_pct']);self.assertIsNone(h.history(db,'US')['series'][0]['points'][0]['return_pct'])
  h.snapshot(self.path,self.now+dt.timedelta(days=1,hours=1))
  with auto.connect(self.path) as db:self.assertEqual(len(h.history(db,'KR')['series'][0]['points']),2)
if __name__=='__main__':unittest.main()
