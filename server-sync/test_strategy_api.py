import datetime
import importlib
import sys
import types
import unittest
from unittest.mock import patch

# No credentials or broker requests are used in these tests.
sys.modules.setdefault('broker_read', types.SimpleNamespace(Client=object))
sys.modules.setdefault('credentials', types.SimpleNamespace(load_credentials=lambda _: None))
strategy = importlib.import_module('strategy_api')


def bars(prices, volumes=None):
    start = datetime.date(2026, 1, 1)
    return [{'dt': (start + datetime.timedelta(days=i)).strftime('%Y%m%d'),
             'cur_prc': str(p), 'high_pric': str(p+1),
             'trde_qty': str(volumes[i] if volumes else 100)} for i, p in enumerate(prices)]


class SignalsTest(unittest.TestCase):
    def test_trend_and_momentum(self):
        result = strategy.signals(list(reversed(bars(list(range(100, 161))))))
        self.assertIn('trend', result['matches'])
        self.assertIn('momentum', result['matches'])
        self.assertNotIn('breakout', result['matches'])

    def test_breakout_excludes_current_high_from_reference(self):
        result = strategy.signals(bars([100]*60+[110], [100]*60+[200]))
        self.assertIn('breakout', result['matches'])

    def test_pullback(self):
        result = strategy.signals(bars(list(range(100, 160))+[151]))
        self.assertIn('pullback', result['matches'])

    def test_reversion(self):
        self.assertIn('reversion', strategy.signals(bars([100]*60+[80]))['matches'])

    def test_flat_series_not_signal(self):
        self.assertEqual(strategy.signals(bars([100]*61))['matches'], {})

    def test_invalid_or_short_history(self):
        for prices in ([100]*60, [100]*60+[0], [100]*60+[float('nan')]):
            with self.assertRaises(ValueError): strategy.signals(bars(prices))
        duplicate = bars([100]*61)
        duplicate[-1]['dt'] = duplicate[-2]['dt']
        with self.assertRaises(ValueError): strategy.signals(duplicate)

    def test_top_ten_partial_failure_and_today_exclusion(self):
        universe = [{'stk_cd': f'{i:06}', 'stk_nm': f'Stock {i}'} for i in range(13)]
        history = bars(list(range(100, 161)))
        today = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).strftime('%Y%m%d')
        def call(client, api, path, body):
            if api == 'ka10032':return {'trde_prica_upper': universe}, {}
            if body['stk_cd'] == '000012':raise RuntimeError('broker unavailable')
            return {'stk_dt_pole_chart_qry': history+[{'dt':today,'cur_prc':'1','high_pric':'1','trde_qty':'100'}]}, {}
        with patch.object(strategy, '_client', return_value=object()), patch.object(strategy, '_call', side_effect=call), patch.object(strategy.time, 'sleep'):
            strategy._state = {'status':'loading','processed':0,'total':0,'failed':0}
            strategy._scan()
        result = strategy.screen('trend')
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(len(result['stocks']), 10)
        self.assertEqual(result['failed'], 1)
        self.assertEqual(result['date'], history[-1]['dt'])
        self.assertEqual(len(set(s['code'] for s in result['stocks'])),10)

    def test_invalid_strategy(self):
        with self.assertRaises(ValueError):strategy.screen('unknown')


if __name__ == '__main__': unittest.main()
