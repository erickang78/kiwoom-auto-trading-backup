import datetime as dt
from auto_performance_period import apply_costs,calculate,KST
from test_real_profit_net import RealProfitNetTests

class PeriodNetTests(RealProfitNetTests):
    def run_period(self,start='2026-01-02T00:00:00+09:00',error=None):
        rows=[dict(r) for r in self.db.execute('SELECT * FROM intents')]
        gross=dict(available=True,capital_base=1000,realized_pnl=80,unrealized_pnl=120,total_pnl=200,closed_trades=1)
        return apply_costs(gross,rows,self.costs,dt.datetime.fromisoformat(start),error)
    def test_new_buy_partial_sell(self):
        self.add('buy',10,100,'2026-01-02T01:00:00+00:00',fee='10');self.add('sell',4,120,'2026-01-03T01:00:00+00:00',fee='2',tax='1')
        p=self.run_period();self.assertEqual(p['realized_pnl'],73);self.assertEqual(p['unrealized_pnl'],114);self.assertEqual(p['total_pnl'],187);self.assertEqual(p['return_pct'],18.7)
    def test_opening_buy_cost_not_charged_again(self):
        self.add('buy',10,100,'2026-01-01T01:00:00+00:00',fee='100');self.add('sell',4,120,'2026-01-03T01:00:00+00:00',fee='2')
        p=self.run_period();self.assertEqual(p['total_pnl'],198);self.assertEqual(p['confirmed_fee'],2);self.assertEqual(p['pending_cost_orders'],0)
    def test_missing_and_corrupt_pending(self):
        self.add('buy',10,100,'2026-01-02T01:00:00+00:00',known=False)
        self.assertTrue(self.run_period()['provisional']);self.assertEqual(self.run_period(error='corrupt')['pending_cost_orders'],1)
    def test_cross_midnight_partial_ambiguous(self):
        r=self.add('buy',10,100,'2026-01-01T01:00:00+00:00');self.db.execute('UPDATE intents SET updated=? WHERE id=?',('2026-01-02T01:00:00+00:00',r['id']))
        self.assertFalse(self.run_period()['available'])
    def test_no_trade_and_no_capital(self):
        p=apply_costs(dict(available=True,capital_base=0,realized_pnl=0,unrealized_pnl=0,total_pnl=0,closed_trades=0),[],[],dt.datetime.now(KST));self.assertIsNone(p['return_pct']);self.assertFalse(p['provisional'])
    def test_kst_boundary_inclusive(self):
        self.add('buy',1,100,'2026-01-01T15:00:00+00:00',fee='1');self.assertEqual(self.run_period()['confirmed_fee'],1)
    def test_period_gross_opening_denominator(self):
        zero=dict(available=True,holding_cost=100,unrealized_pnl=20,cumulative_buy_amount=100,realized_pnl=0,closed_trades=0,winning_trades=0)
        current=dict(zero,cumulative_buy_amount=200,unrealized_pnl=40)
        p=calculate(current,zero,3,dt.datetime.now(KST),dt.datetime.now(KST));self.assertEqual(p['capital_base'],220);self.assertEqual(p['total_pnl'],20)
