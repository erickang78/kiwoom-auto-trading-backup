import copy
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import signal_validation as s

NOW = dt.datetime(2026, 9, 24, 14, 0, tzinfo=dt.timezone.utc)

def scan(count=1):
    return {'status': 'ready', 'date': '20260923', 'stocks': [
        {'code': f'S{i}', 'exchange': 'ND', 'name': f'Stock {i}', 'reason': 'trend'}
        for i in range(count)]}

def quotes(count=1, price='50', volume='100', fx='1300'):
    return {f'ND:S{i}': {'cur_prc': price, 'acc_trde_qty': volume, 'base_exrt': fx} for i in range(count)}

class ValidationTest(unittest.TestCase):
    def test_worker_uses_trend_and_reports_candidate_count(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(s.time, 'sleep'):
            path = Path(tmp) / 'state.db'
            called = []
            def screen(strategy):
                called.append(strategy)
                return scan()
            s.cycle(path, NOW, screen, lambda *args: {'quote': quotes()['ND:S0']})
            s.cycle(path, NOW + dt.timedelta(minutes=1), screen,
                    lambda *args: {'quote': quotes(volume='101')['ND:S0']})
            result = s.status(path=path)
            self.assertEqual(called, ['trend', 'trend'])
            self.assertEqual(result['rules']['strategy'], 'trend')
            self.assertEqual(result['scan']['candidates'], 1)
            self.assertEqual(result['positions'][0]['strategy'], 'trend')
            self.assertFalse(result['orders_enabled'])

    def test_empty_candidates_are_explained(self):
        state = s.initial(NOW)
        self.assertFalse(s.step(state, scan(0), {}, NOW))
        self.assertEqual(state['scan']['candidates'], 0)
        self.assertTrue(any('후보 0개' in issue for issue in state['issues']))

    def enter(self, count=1):
        state = s.initial(NOW)
        self.assertEqual(s.step(state, scan(count), quotes(count), NOW), [])
        events = s.step(state, scan(count), quotes(count, volume='101'), NOW + dt.timedelta(minutes=1))
        return state, events

    def test_one_share_capacity_duplicate_restart(self):
        state, events = self.enter(7)
        self.assertEqual(len(events), 5)
        self.assertEqual(len(state['positions']), 5)
        self.assertTrue(all(p['quantity'] == 1 for p in state['positions'].values()))
        state = __import__('json').loads(__import__('json').dumps(state))
        self.assertEqual(s.step(state, scan(7), quotes(7, volume='102'), NOW + dt.timedelta(minutes=2)), [])

    def test_exact_take_profit_and_no_same_signal_reentry(self):
        state, _ = self.enter()
        events = s.step(state, scan(), quotes(price='52.5', volume='102'), NOW + dt.timedelta(minutes=2))
        self.assertEqual([e['kind'] for e in events], ['SELL'])
        self.assertEqual(events[0]['reason'], '익절 +5%')
        self.assertAlmostEqual(state['realized_pnl'], 2.5)
        self.assertFalse(state['positions'])

    def test_stop_even_when_scanner_unavailable(self):
        state, _ = self.enter()
        events = s.step(state, {'status': 'error'}, quotes(price='48.5', volume='102'), NOW + dt.timedelta(minutes=2))
        self.assertEqual(events[0]['reason'], '손절 -3%')
        self.assertAlmostEqual(events[0]['pnl'], -1.5)

    def test_no_trade_without_updating_volume_or_after_long_gap(self):
        state, _ = self.enter()
        events = s.step(state, scan(), quotes(price='40', volume='101'), NOW + dt.timedelta(minutes=2))
        self.assertFalse(events)
        events = s.step(state, scan(), quotes(price='40', volume='102'), NOW + dt.timedelta(minutes=10))
        self.assertFalse(events)
        self.assertEqual(len(state['positions']), 1)

    def test_expensive_stock_bought_once(self):
        state = s.initial(NOW)
        s.step(state, scan(), quotes(price='1000'), NOW)
        events = s.step(state, scan(), quotes(price='1000', volume='101'), NOW + dt.timedelta(minutes=1))
        self.assertEqual(events[0]['kind'], 'BUY')
        self.assertEqual(state['positions']['ND:S0']['quantity'], 1)
        self.assertEqual(state['positions']['ND:S0']['cost_krw'], 1300000)
        self.assertFalse(s.step(state, scan(), quotes(price='1000', volume='102'), NOW + dt.timedelta(minutes=2)))

    def test_bad_fx_price_volume(self):
        for field in ['cur_prc', 'acc_trde_qty', 'base_exrt']:
            for value in ['0', 'NaN', 'inf', '', None]:
                state = s.initial(NOW)
                s.step(state, scan(), quotes(), NOW)
                q = quotes(volume='101'); q['ND:S0'][field] = value
                self.assertFalse(s.step(state, scan(), q, NOW + dt.timedelta(minutes=1)))
                self.assertFalse(state['positions'])

    def test_outside_session_weekend_and_stale_signal(self):
        for now in [NOW.replace(hour=12), NOW + dt.timedelta(days=2)]:
            state = s.initial(now)
            self.assertFalse(s.step(state, scan(), quotes(), now))
            self.assertEqual(state['status'], 'outside_session')
        state = s.initial(NOW)
        s.step(state, scan(), quotes(), NOW)
        for date in ['20260924', '20260925', '20260910', 'bad']:
            ss = copy.deepcopy(state)
            self.assertFalse(s.step(ss, dict(scan(), date=date), quotes(volume='101'), NOW + dt.timedelta(minutes=1)))

    def test_mid_price_stock_buys_two_shares_by_krw_value(self):
        state = s.initial(NOW)
        s.step(state, scan(), quotes(price='25', fx='1000'), NOW)
        s.step(state, scan(), quotes(price='25', fx='1000', volume='101'), NOW + dt.timedelta(minutes=1))
        self.assertEqual(state['positions']['ND:S0']['quantity'], 2)
        self.assertEqual(state['positions']['ND:S0']['cost_krw'], 50000)

    def test_db_persistence_pause_and_read_only_calls(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(s.time, 'sleep'):
            path = Path(tmp) / 'state.db'
            screen_fn = lambda strategy: scan()
            q = lambda code, exchange: {'quote': quotes()['ND:S0']}
            s.cycle(path, NOW, screen_fn, q)
            q2 = lambda code, exchange: {'quote': quotes(volume='101')['ND:S0']}
            s.cycle(path, NOW + dt.timedelta(minutes=1), screen_fn, q2)
            result = s.status(path=path)
            self.assertEqual(len(result['positions']), 1)
            self.assertEqual(len(result['events']), 1)
            self.assertFalse(result['orders_enabled'])
            s.status('pause', path)
            def fail(*args): raise AssertionError('paused worker must not query')
            s.cycle(path, NOW, fail, fail)
            self.assertFalse(s.status(path=path)['enabled'])
            self.assertTrue(s.status('resume', path)['enabled'])
            with self.assertRaises(ValueError): s.status('live', path)

    def test_pause_during_fetch_discards_pending_purchase(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(s.time, 'sleep'):
            path = Path(tmp) / 'state.db'
            s.cycle(path, NOW, lambda _: scan(), lambda *args: {'quote': quotes()['ND:S0']})
            def pause(*args):
                s.status('pause', path)
                return {'quote': quotes(volume='101')['ND:S0']}
            s.cycle(path, NOW + dt.timedelta(minutes=1), lambda _: scan(), pause)
            self.assertFalse(s.status(path=path)['positions'])
            self.assertFalse(s.status(path=path)['events'])


class MultiPortfolioTest(unittest.TestCase):
    def test_all_ten_portfolios_trade_and_pause_independently(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(s.time, 'sleep'):
            path = Path(tmp) / 'state.db'
            for market in ('US', 'KR'):
                now = NOW if market == 'US' else NOW.replace(hour=1)
                for strategy in s.STRATEGIES:
                    def screen(key):
                        self.assertEqual(key, strategy)
                        data = scan()
                        if market == 'KR':
                            data['stocks'][0].pop('exchange')
                        return data
                    for minute in (0, 1):
                        q = dict(quotes(volume=str(100 + minute))['ND:S0'], trde_qty=str(100 + minute))
                        s.cycle(path, now + dt.timedelta(minutes=minute), screen, lambda *args: {'quote': q}, market, strategy)
                    result = s.status(path=path, market=market, strategy=strategy)
                    self.assertEqual(len(result['positions']), 1)
                    self.assertEqual(result['positions'][0]['strategy'], strategy)
                    self.assertEqual(result['performance']['return_pct'], 0)
                    self.assertEqual(result['currency'], 'USD' if market == 'US' else 'KRW')
            s.status('pause', path, 'KR', 'momentum')
            self.assertFalse(s.status(path=path, market='KR', strategy='momentum')['enabled'])
            self.assertTrue(s.status(path=path, market='US', strategy='momentum')['enabled'])
            self.assertTrue(s.status(path=path, market='KR', strategy='trend')['enabled'])

    def test_performance_closed_and_open_and_empty(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'state.db'
            self.assertIsNone(s.status(path=path)['performance']['return_pct'])
            with s.connect(path) as db:
                state = s.initial(NOW)
                state['positions']['ND:B'] = dict(entry_price=100, last_price=102, quantity=1)
                db.execute('UPDATE state SET data=? WHERE id=1', (json.dumps(state),))
                # More than the displayed 100 events must still count toward returns.
                for i in range(101):
                    db.execute('INSERT INTO events(data,portfolio) VALUES (?,1)', (json.dumps(dict(kind='SELL', entry_price=100, quantity=1, pnl=5)),))
            result = s.status(path=path)
            self.assertEqual(len(result['events']), 100)
            perf = result['performance']
            self.assertEqual(perf['closed_trades'], 101)
            self.assertEqual(perf['total_pnl'], 507)
            self.assertEqual(perf['win_rate_pct'], 100)
            self.assertAlmostEqual(perf['return_pct'], 507 / 10200 * 100)
            self.assertIsNone(s.status(path=path, market='KR')['performance']['return_pct'])

    def test_legacy_db_records_and_pause_preserved(self):
        import sqlite3, json
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'state.db'
            state = s.initial(NOW)
            state['positions']['ND:S0'] = dict(entry_usd=50, last_usd=51, quantity=1)
            with sqlite3.connect(path) as db:
                db.execute('CREATE TABLE state (id INTEGER PRIMARY KEY, enabled INTEGER, revision INTEGER, data TEXT)')
                db.execute('CREATE TABLE events (id INTEGER PRIMARY KEY, data TEXT NOT NULL)')
                db.execute('INSERT INTO state VALUES (1,0,7,?)', (json.dumps(state),))
                db.execute('INSERT INTO events(data) VALUES (?)', (json.dumps(dict(kind='SELL',entry_usd=40, quantity=1,pnl_usd=2)),))
            for _ in range(2):
                result = s.status(path=path)
                self.assertFalse(result['enabled'])
                self.assertEqual(result['positions'][0]['entry_price'], 50)
                self.assertEqual(result['performance']['total_pnl'], 3)
                self.assertEqual(len(result['events']), 1)
                self.assertEqual(s.status(path=path, market='KR')['events'], [])

    def test_market_hours_and_invalid_selection(self):
        self.assertTrue(s.regular_window(NOW.replace(hour=1), 'KR'))
        self.assertFalse(s.regular_window(NOW, 'KR'))
        self.assertFalse(s.regular_window(NOW.replace(hour=6, minute=30), 'KR'))
        for market, strategy in [('JP','trend'),('US','invalid')]:
            with self.assertRaises(ValueError):
                s.status(market=market, strategy=strategy)

if __name__ == '__main__': unittest.main()
