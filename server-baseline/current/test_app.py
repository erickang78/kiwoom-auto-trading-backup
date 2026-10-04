import unittest
from app import Portfolio, simulate, synthetic_data, targets


class PortfolioTests(unittest.TestCase):
    def test_deposit_does_not_erase_loss(self):
        p = Portfolio()
        prices = {'KR': 100, 'US': 100, 'GOLD': 100}
        p.deposit(1000, prices)
        p.cash = 0
        p.qty['KR'] = 10
        prices['KR'] = 70
        self.assertAlmostEqual(p.drawdown(prices), .30)
        p.deposit(1000, prices)
        self.assertAlmostEqual(p.drawdown(prices), .30)

    def test_whole_units_and_cash_limit(self):
        p = Portfolio()
        prices = {'KR': 35000, 'US': 80000, 'GOLD': 180000}
        p.deposit(1_000_000, prices)
        p.trade(prices, {'KR': .3, 'US': .4, 'GOLD': .15})
        self.assertEqual(p.qty['GOLD'], 0)
        self.assertGreaterEqual(p.cash, 150_000)
        self.assertTrue(all(isinstance(n, int) for n in p.qty.values()))

    def test_halt_prevents_orders(self):
        p = Portfolio()
        p.halted = True
        self.assertEqual(p.trade(dict.fromkeys(('KR', 'US', 'GOLD'), 10), {'KR': .3, 'US': .4, 'GOLD': .15}), [])

    def test_demo_has_52_deposits_and_no_negative_cash(self):
        r = simulate(synthetic_data())
        self.assertEqual(len(r['records']), 52)
        self.assertEqual(r['records'][-1]['deposits'], 6_200_000)
        self.assertTrue(all(x['cash'] >= 0 for x in r['records']))

    def test_future_does_not_change_past(self):
        rows = synthetic_data()
        first = simulate(rows)['records'][:10]
        for row in rows[70:]:
            row['US'] *= 10
        self.assertEqual(first, simulate(rows)['records'][:10])

    def test_downtrend_holds_gold_and_cash(self):
        rows = [{a: 100-i for a in ('KR', 'US', 'GOLD')} for i in range(53)]
        self.assertEqual(targets(rows), {'KR': 0, 'US': 0, 'GOLD': .15})

    def test_reject_bad_data(self):
        rows = synthetic_data()
        rows[-1]['KR'] = float('nan')
        with self.assertRaises(ValueError):
            simulate(rows)


if __name__ == '__main__':
    unittest.main()
