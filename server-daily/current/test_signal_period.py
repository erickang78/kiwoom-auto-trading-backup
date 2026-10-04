import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
import signal_validation as s

NOW = dt.datetime(2026, 9, 30, 6, tzinfo=dt.timezone.utc)
class PeriodTests(unittest.TestCase):
    def test_boundaries_baseline_and_all_windows(self):
        with tempfile.TemporaryDirectory() as tmp:
            with s.connect(Path(tmp)/'signals.db') as db:
                p=dict(code='A',exchange='KRX',entry_at='2026-09-22T01:00:00+00:00',entry_price=100,quantity=1,last_price=120)
                db.execute('INSERT INTO daily_marks VALUES (?,?,?,?)',(6,'2026-09-25','',json.dumps({'KRX:A':dict(p,last_price=110)})))
                for days in (5,10,30,50,100):
                    r=s.period_performance(db,6,[p],days,NOW)
                    self.assertAlmostEqual(r['total_pnl'],10 if days==5 else 20)
                    self.assertAlmostEqual(r['return_pct'],1000/110 if days==5 else 20)
                sell=dict(p,kind='SELL',at='2026-09-25T15:00:00+00:00',reference_price=115,pnl=15)
                db.execute('INSERT INTO events(data,portfolio) VALUES (?,?)',(json.dumps(sell),6))
                r=s.period_performance(db,6,[],5,NOW)
                self.assertEqual(r['realized_pnl'],5)
                self.assertEqual(r['closed_trades'],1)
                self.assertEqual(s.period_performance(db,1,[],5,NOW)['closed_trades'],0)
    def test_missing_empty_invalid_and_future(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'signals.db'
            with s.connect(path) as db:
                p=dict(code='A',entry_at='2026-09-22T01:00:00+00:00',entry_price=100,quantity=1,last_price=120)
                r=s.period_performance(db,6,[p],5,NOW)
                self.assertFalse(r['available']);self.assertIsNone(r['return_pct'])
                self.assertIsNone(s.period_performance(db,6,[],5,NOW)['return_pct'])
                p['entry_at']='2026-10-01T00:00:00+00:00'
                self.assertIsNone(s.period_performance(db,6,[p],5,NOW)['return_pct'])
            for invalid in (0,6,'5',True,None):
                if invalid is not None:
                    with self.assertRaises(ValueError):s.status(path=path,days=invalid)
    def test_pause_resume_preserves_records(self):
        import trading_control as c
        import trading_api as t
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'signals.db';gate=Path(tmp)/'trading-control.sqlite3'
            with s.connect(path) as db:
                db.execute('INSERT INTO events(data,portfolio) VALUES (?,?)',(json.dumps({'kind':'BUY','at':s.stamp(NOW)}),6))
                state=db.execute('SELECT id,data FROM state').fetchall()
                events=db.execute('SELECT * FROM events').fetchall()
            with patch.object(t,'DB',Path(tmp)/'orders.db'):
                with t.connection() as orders:
                    orders.execute('INSERT INTO orders VALUES (?,?,?,?,?)',('test',1,'{}','accepted','{}'))
                for action in ('pause','resume','pause'):
                    c.status(action,gate,path)
                    with s.connect(path) as db:
                        self.assertEqual(state,db.execute('SELECT id,data FROM state').fetchall())
                        self.assertEqual(events,db.execute('SELECT * FROM events').fetchall())
                    with t.connection() as orders:
                        self.assertEqual(orders.execute('SELECT status FROM orders').fetchone()[0],'accepted')
