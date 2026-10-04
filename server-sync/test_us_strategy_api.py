import copy
import unittest
from unittest.mock import patch
from test_strategy_api import bars
import strategy_api as kr
import us_strategy_api as us


class USStrategyTest(unittest.TestCase):
    def setUp(self):
        self.state, self.expires = copy.deepcopy(us._state), us._expires
        self.addCleanup(lambda: setattr(us, '_state', self.state))
        self.addCleanup(lambda: setattr(us, '_expires', self.expires))

    def test_scan_mapping_dates_failure_stale_top_ten(self):
        universe = [{'stk_cd': f'S{i}', 'stex_tp': 'ND', 'stk_nm': f'Stock {i}'} for i in range(14)]
        history = [dict(r, acc_trde_qty=r['trde_qty']) for r in bars(list(range(100, 161)))]
        def call(client, api, path, body):
            if api == 'usa20540':
                self.assertEqual(body['stk_tp'], '1')
                return {'result_list': universe+[universe[0], {'stk_cd':'BAD','stex_tp':'XX'}]}, {}
            self.assertEqual(api, 'usa06012')
            self.assertEqual(body['strt_dt'], '20260924')
            self.assertEqual(body['exrt_appl_tp'], '0')
            self.assertEqual(body['stex_tp'], 'ND')
            if body['stk_cd'] == 'S13': raise RuntimeError('offline')
            rows = history
            if body['stk_cd'] == 'S12': rows = [dict(r, dt=str(int(r['dt'])-1)) for r in history]
            return {'result_list': rows+[{'dt':'20260924','cur_prc':'1','high_pric':'1','acc_trde_qty':'100'}]}, {}
        old_kr = copy.deepcopy(kr._state)
        with patch.object(us, '_client', return_value=object()), patch.object(us, '_call', side_effect=call), patch.object(us, '_today', return_value='20260924'), patch.object(us.time, 'sleep'):
            us._state = {'status':'loading','processed':0,'total':0,'failed':0}
            us._scan()
        r = kr.screen('trend', 'US')
        self.assertEqual((r['status'],r['total'],r['failed'],r['stale']), ('ready',14,1,1))
        self.assertEqual((r['market'],r['currency'],r['date']), ('US','USD',history[-1]['dt']))
        self.assertEqual(len(r['stocks']),10)
        self.assertEqual(r['stocks'][0]['exchange'],'ND')
        self.assertFalse(r['orders_enabled'])
        self.assertEqual(kr._state,old_kr)
        r['stocks'].clear()
        self.assertEqual(len(us.screen()['stocks']),10)

    def test_market_validation(self):
        with self.assertRaises(ValueError): kr.screen('trend','XX')
        with self.assertRaises(ValueError): kr.screen('unknown','US')

    def test_empty_and_all_failed(self):
        for rows in ([],[{'stk_cd':'AAPL','stex_tp':'ND'}]):
            with patch.object(us,'_client',return_value=object()), patch.object(us,'_call',return_value=({'result_list':rows},{})), patch.object(us.time,'sleep'):
                us._state={'status':'loading','processed':0,'total':0,'failed':0}
                us._scan()
            self.assertEqual(us.screen()['status'],'error')

    def test_duplicate_request_reuses_worker_and_cache(self):
        us._state={'status':'idle','processed':0,'total':0,'failed':0}
        us._expires=0
        with patch.object(us.threading,'Thread') as thread:
            self.assertEqual(us.screen()['status'],'loading')
            self.assertEqual(us.screen('momentum')['status'],'loading')
            thread.assert_called_once()

if __name__ == '__main__': unittest.main()
