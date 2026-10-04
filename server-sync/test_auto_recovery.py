import json
from unittest.mock import patch
from test_auto_trading import AutoTests,NOW
import auto_trading as auto

class RestartTests(AutoTests):
    def restart(self,holdings=None,reports=None,**body):
        with patch.object(auto.trade,'client',return_value=object()),patch.object(auto,'account',return_value=(holdings or {},holdings or {},set())),patch.object(auto,'order_rows',return_value=reports or []),patch.object(auto,'send') as send:
            value=auto.control(dict(market='KR',strategy='trend',action='start',confirmed=True,budget='500000',**body),self.db,self.gate)
            send.assert_not_called()
            return value
    def test_missing_number_requires_user_confirmation_not_assumption(self):
        self.run_cycle(send_status='unknown')
        value=self.restart()
        self.assertFalse(value['enabled']);self.assertEqual(value['restart_check']['result'],'blocked')
        self.assertTrue(value['restart_check']['orders'][0]['can_confirm_absent'])
        self.assertEqual(value['orders'][0]['status'],'unknown')
        self.assertIn('주문',value['stop_reason']['reason'])
    def test_confirmed_absence_rechecks_and_restarts_without_resending_old_order(self):
        self.run_cycle(send_status='unknown');value=self.restart(confirmed_absent_orders=[1])
        self.assertTrue(value['enabled']);self.assertEqual(value['orders'][0]['status'],'failed')
        self.assertEqual(value['orders'][0]['failure']['kind'],'not_submitted_confirmed')
        self.assertEqual(len(self.sent),1)
        self.seed();self.run_cycle();self.assertEqual(len(self.sent),2)
        self.assertEqual(len(self.status()['orders']),2)
    def test_relevant_order_blocks_even_user_absence_confirmation(self):
        self.run_cycle(send_status='unknown')
        report=dict(ord_no='123',stk_cd='A005930',ord_tm='10:10:00')
        value=self.restart(reports=[report],confirmed_absent_orders=[1])
        self.assertFalse(value['enabled']);self.assertFalse(value['restart_check']['orders'][0]['can_confirm_absent'])
        self.assertEqual(value['orders'][0]['status'],'unknown')
    def test_missing_order_time_cannot_prove_absence(self):
        self.run_cycle(send_status='unknown')
        value=self.restart(reports=[dict(stk_cd='A005930')],confirmed_absent_orders=[1])
        self.assertFalse(value['enabled']);self.assertFalse(value['restart_check']['orders'][0]['can_confirm_absent'])
    def test_external_holding_blocks_absence(self):
        self.run_cycle(send_status='unknown');value=self.restart(holdings={'005930':1},confirmed_absent_orders=[1])
        self.assertFalse(value['enabled']);self.assertEqual(value['orders'][0]['status'],'unknown')
    def test_known_order_fill_recovers_automatically(self):
        self.run_cycle();auto.control({'market':'KR','action':'stop'},self.db,self.gate)
        value=self.restart(holdings={'005930':1},reports=[dict(ord_no='123',stk_cd='A005930',cntr_qty='1',ord_remnq='0',cntr_uv='70000')])
        self.assertTrue(value['enabled']);self.assertEqual(value['orders'][0]['status'],'filled');self.assertEqual(value['positions'][0]['quantity'],1)
    def test_account_failure_does_not_start_or_leak_exception(self):
        auto.control({'market':'KR','action':'stop'},self.db,self.gate)
        with patch.object(auto.trade,'client',side_effect=RuntimeError('secret 123456')):
            value=auto.control(dict(market='KR',action='start',confirmed=True,budget='500000'),self.db,self.gate)
        self.assertFalse(value['enabled']);self.assertNotIn('secret',json.dumps(value))
    def test_check_does_not_start(self):
        auto.control({'market':'KR','action':'stop'},self.db,self.gate)
        with patch.object(auto.trade,'client',return_value=object()),patch.object(auto,'account',return_value=({}, {}, set())):
            value=auto.control({'market':'KR','action':'check_restart'},self.db,self.gate)
        self.assertFalse(value['enabled']);self.assertEqual(value['restart_check']['result'],'ready')
    def test_multiple_unknowns_are_atomic(self):
        self.run_cycle(send_status='unknown')
        with auto.connect(self.db) as db:
            p=dict(market='KR',side='buy',code='000001',quantity='1',price='70000',exchange='KRX',name='Other')
            db.execute("INSERT INTO intents(market,strategy,dedup,payload,status,number,created,updated) VALUES ('KR','trend','other',?,'unknown','',?,?)",(json.dumps(p),auto.stamp(NOW),auto.stamp(NOW)))
        value=self.restart(confirmed_absent_orders=[1])
        self.assertFalse(value['enabled']);self.assertTrue(all(x['status']=='unknown' for x in value['orders']))
