import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import trading_api as t


class TradingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = t.DB
        t.DB = Path(self.tmp.name) / 'orders.sqlite3'
        self.order = dict(mode='real', market='US', side='buy', code='AAPL', quantity='2', price='100.25', exchange='ND')

    def tearDown(self):
        t.DB = self.old
        self.tmp.cleanup()

    def test_request_mapping(self):
        api, path, body = t.order_request(t.normalize_order(self.order))
        self.assertEqual((api, path, body['trde_tp'], body['ord_uv']), ('ust20000', '/api/us/ordr', '00', '100.25'))
        order = dict(self.order, market='KR', code='005930', price='1000', side='sell')
        api, path, body = t.order_request(t.normalize_order(order))
        self.assertEqual((api, path, body['dmst_stex_tp'], body['trde_tp']), ('kt10001', '/api/dostk/ordr', 'KRX', '0'))

    @patch.object(t, 'call')
    @patch.object(t, 'client')
    def test_all_four_previews_do_not_submit(self, client, call):
        for market, side, api in [('US', 'buy', 'ust20000'), ('US', 'sell', 'ust20001'),
                                  ('KR', 'buy', 'kt10000'), ('KR', 'sell', 'kt10001')]:
            with self.subTest(market=market, side=side):
                order = dict(self.order, market=market, side=side,
                             code='AAPL' if market == 'US' else '005930',
                             price='100.25' if market == 'US' else '70000')
                result = t.route('/v1/trade/preview', order)
                self.assertEqual(result['order']['side'], side)
                self.assertEqual(result['order']['market'], market)
                self.assertEqual(result['currency'], 'USD' if market == 'US' else 'KRW')
                self.assertEqual(t.order_request(result['order'])[0], api)
                self.assertEqual(result['total'], '200.50' if market == 'US' else '140000')
        client.assert_not_called()
        call.assert_not_called()

    def test_invalid_values(self):
        for key, value in [('quantity', '0'), ('quantity', '-1'), ('quantity', '1.5'), ('quantity', True), ('price', 'NaN'), ('price', '0'), ('price', '1e3'), ('price', '0.00001'), ('mode', 'mock'), ('exchange', 'BAD'), ('code', 'AAPL;')]:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                t.normalize_order(dict(self.order, **{key: value}))

    @patch.object(t, 'call', return_value=({'ord_no': '12345'}, None))
    @patch.object(t, 'client')
    def test_duplicate_submission_never_repeats(self, client, call):
        p = t.preview(self.order)
        self.assertEqual(p['total'], '200.50')
        body = dict(preview_id=p['preview_id'], confirmed=True)
        self.assertEqual(t.submit(body)['status'], 'accepted')
        self.assertEqual(t.submit(body)['order_number'], '12345')
        call.assert_called_once()

    @patch.object(t, 'call', side_effect=TimeoutError)
    @patch.object(t, 'client')
    def test_timeout_is_not_retried(self, client, call):
        body = dict(preview_id=t.preview(self.order)['preview_id'], confirmed=True)
        self.assertEqual(t.submit(body)['status'], 'unknown')
        self.assertEqual(t.submit(body)['status'], 'unknown')
        call.assert_called_once()

    @patch.object(t, 'client')
    def test_expiration_and_confirmation(self, client):
        p = t.preview(self.order)
        with self.assertRaises(ValueError):
            t.submit({'preview_id': p['preview_id']})
        with patch.object(t.time, 'time', return_value=t.time.time() + 121), self.assertRaises(ValueError):
            t.submit({'preview_id': p['preview_id'], 'confirmed': True})
        client.assert_not_called()


if __name__ == '__main__':
    unittest.main()
