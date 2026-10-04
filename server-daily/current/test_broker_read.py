import unittest
from unittest.mock import patch
from broker_read import Client, BrokerError, snapshot


class ReadTests(unittest.TestCase):
    @patch('broker_read.time.sleep')
    def test_pagination_and_order_block(self, _):
        c = Client()
        c.token = 'test'
        calls = []
        def post(path, body, headers):
            calls.append(headers)
            return ({'return_code': 0}, ('Y', 'page2') if len(calls) == 1 else ('N', ''))
        c._post = post
        self.assertEqual(len(list(c.pages('kt00018', {}))), 2)
        self.assertEqual(calls[1]['next-key'], 'page2')
        with self.assertRaises(BrokerError):
            list(c.pages('kt10000', {}))
        self.assertEqual(len(calls), 2)

    @patch('broker_read.time.sleep')
    def test_repeated_cursor_fails(self, _):
        c = Client()
        c.token = 'test'
        c._post = lambda *a: ({}, ('Y', 'same'))
        with self.assertRaises(BrokerError):
            list(c.pages('kt00018', {}))

    def test_snapshot_merges_and_filters(self):
        c = Client()
        c.pages = lambda api, body: iter([
            {'acnt_evlt_remn_indv_tot': [{'stk_cd': 'A', 'rmnd_qty': '2'}], 'token': 'SECRET'},
            {'acnt_evlt_remn_indv_tot': [{'stk_cd': 'B', 'rmnd_qty': '3'}]}]
            if api == 'kt00018' else [{'cur_prc': '-123', 'token': 'SECRET'}])
        r = snapshot(c, '005930')
        self.assertEqual(len(r['holdings']), 2)
        self.assertEqual(r['quote']['cur_prc'], '-123')
        self.assertNotIn('SECRET', str(r))
        self.assertFalse(r['orders_enabled'])
        with self.assertRaises(BrokerError):
            snapshot(c, '../bad')

    def test_missing_holdings_not_silently_empty(self):
        c = Client()
        c.pages = lambda *a: iter([{}])
        with self.assertRaises(BrokerError):
            snapshot(c, '005930')


if __name__ == '__main__':
    unittest.main()
