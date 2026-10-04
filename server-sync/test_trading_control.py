import concurrent.futures
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
import trading_control as c
import trading_api as t
import signal_validation as s
from test_signal_validation import NOW, scan, quotes
import datetime as dt

class ControlTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.gate=self.root/'trading-control.sqlite3';self.signals=self.root/'signals.db'
        self.patch=patch.object(t,'DB',self.root/'orders.db');self.patch.start()
    def tearDown(self):
        self.patch.stop();self.tmp.cleanup()
    def control(self,action='status'):
        return c.status(action,self.gate,self.signals)
    def test_persistence_all_ten_and_scoped_resume_cannot_bypass(self):
        self.assertTrue(self.control()['enabled'])
        self.control('pause')
        for market in ('KR','US'):
            for strategy in s.STRATEGIES:
                self.assertFalse(s.status('resume',self.signals,market,strategy)['enabled'])
                s.cycle(self.signals,NOW,lambda _:self.fail('paused scan'),market=market,strategy=strategy)
        self.assertFalse(self.control()['enabled'])
        self.control('resume')
        for market in ('KR','US'):
            for strategy in s.STRATEGIES:
                self.assertTrue(s.status(path=self.signals,market=market,strategy=strategy)['enabled'])
    @patch.object(s.time,'sleep')
    def test_inflight_paper_fill_discarded_on_pause_and_quick_resume(self,_):
        s.cycle(self.signals,NOW,lambda _:scan(),lambda *a:{'quote':quotes()['ND:S0']})
        def quote(*a):
            self.control('pause');self.control('resume')
            return {'quote':quotes(volume='101')['ND:S0']}
        s.cycle(self.signals,NOW+dt.timedelta(minutes=1),lambda _:scan(),quote)
        self.assertEqual(s.status(path=self.signals)['events'],[])
        s.cycle(self.signals,NOW+dt.timedelta(minutes=2),lambda _:scan(),lambda *a:{'quote':quotes(volume='102')['ND:S0']})
        self.assertEqual(len(s.status(path=self.signals)['events']),1)
    @patch.object(t,'client')
    @patch.object(t,'call',return_value=({'ord_no':'123'},None))
    def test_real_mock_both_sides_block_and_resume(self,call,client):
        for mode in ('mock','real'):
            for side in ('buy','sell'):
                body={'preview_id':t.preview(dict(mode=mode,market='KR',side=side,code='005930',quantity='1',price='1000'))['preview_id'],'confirmed':True}
                self.control('pause')
                with self.assertRaisesRegex(ValueError,'trading_paused'):t.submit(body)
                self.control('resume')
                self.assertEqual(t.submit(body)['status'],'accepted')
        self.assertEqual(call.call_count,4)
    def test_stop_waits_for_inflight_broker_then_blocks_new_orders(self):
        entered=threading.Event();release=threading.Event();stopping=threading.Event()
        def sending():
            with c.permit(self.gate):entered.set();release.wait(3)
        def stop():
            stopping.set();return self.control('pause')
        with concurrent.futures.ThreadPoolExecutor() as pool:
            sent=pool.submit(sending);self.assertTrue(entered.wait(2))
            stopped=pool.submit(stop);self.assertTrue(stopping.wait(2));self.assertFalse(stopped.done())
            release.set();sent.result();self.assertFalse(stopped.result()['enabled'])
        with self.assertRaisesRegex(ValueError,'trading_paused'):
            with c.permit(self.gate):self.fail('must not send')
    def test_invalid_action(self):
        with self.assertRaises(ValueError):self.control('toggle')

if __name__=='__main__':unittest.main()
