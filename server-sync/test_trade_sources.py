import datetime as dt
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import trade_sources as t
import trading_api


class OriginTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        with sqlite3.connect(self.root/'auto-trading.sqlite3') as db:
            db.execute('CREATE TABLE intents (payload TEXT,status TEXT,number TEXT,created TEXT)')
            db.execute('INSERT INTO intents VALUES (?,?,?,?)', (json.dumps(dict(mode='real',market='KR',code='005930')), 'filled', '00012', '2026-09-29T23:59:00+00:00'))
        with sqlite3.connect(self.root/'manual-orders.sqlite3') as db:
            db.execute('CREATE TABLE orders (payload TEXT,status TEXT,result TEXT,created REAL)')
            db.execute('INSERT INTO orders VALUES (?,?,?,?)', (json.dumps(dict(mode='real',market='US',code='AAPL')), 'accepted', '{"order_number":"12"}', dt.datetime(2026,9,30,tzinfo=dt.timezone.utc).timestamp()))

    def tearDown(self):
        self.tmp.cleanup()

    def snapshot(self, **changes):
        return dict(mode='REAL_READ_ONLY', retrieved_at='2026-09-30T01:00:00+00:00', executions=[dict(ord_no='12',stk_cd='A005930')], us=dict(executions=[dict(ord_no='12',stk_cd='AAPL')]), **changes)

    def test_origin_date_market_mode_and_external_manual(self):
        b=self.snapshot()
        b['executions'] += [dict(ord_no='13',stk_cd='000660'),dict(ord_no='12',stk_cd='000660'),dict(ord_no='12',stk_cd='005930',ord_dt='20260929')]
        t.annotate_snapshot(b,self.root)
        self.assertEqual([x['trading_source'] for x in b['executions']], ['automatic','manual','unknown','manual'])
        self.assertEqual(b['us']['executions'][0]['trading_source'],'manual')
        b=self.snapshot();b['mode']='MOCK_READ_ONLY';t.annotate_snapshot(b,self.root)
        self.assertEqual(b['executions'][0]['trading_source'],'manual')

    def test_unresolved_or_missing_ledger_never_claims_manual(self):
        with sqlite3.connect(self.root/'auto-trading.sqlite3') as db:
            db.execute('INSERT INTO intents VALUES (?,?,?,?)', (json.dumps(dict(mode='real',market='KR',code='000660')), 'unknown', '', '2026-09-30T01:00:00+00:00'))
        b=self.snapshot();b['executions'][0]['ord_no']='15';t.annotate_snapshot(b,self.root)
        self.assertEqual(b['executions'][0]['trading_source'],'unknown')
        (self.root/'auto-trading.sqlite3').unlink()
        b=self.snapshot();t.annotate_snapshot(b,self.root)
        self.assertEqual(b['executions'][0]['trading_source'],'unknown')
        self.assertFalse((self.root/'auto-trading.sqlite3').exists())

    def test_manual_origin_cannot_be_spoofed(self):
        o=trading_api.normalize_order(dict(mode='real',market='KR',side='buy',code='005930',quantity='1',price='1000',trading_source='automatic'))
        self.assertEqual(o['trading_source'],'manual')
