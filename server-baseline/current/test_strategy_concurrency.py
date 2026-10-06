"""Synthetic-only multi-strategy safety checks; no broker or persistent state."""
import concurrent.futures
import datetime as dt
import json
import sqlite3
import tempfile
import threading
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
import auto_trading as auto
import strategy_budget as budgets
import trading_control
from signal_validation import initial, STRATEGIES

NOW=dt.datetime(2026,9,30,1,10,tzinfo=dt.timezone.utc)

class StrategyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.db=Path(self.tmp.name)/'auto.sqlite3';self.gate=Path(self.tmp.name)/'control.sqlite3'
        with auto.connect(self.db):pass
        self.addCleanup(patch.stopall)
        patch.object(auto.time,'sleep').start()
        patch.object(auto,'stock_market',return_value='10').start()
        self.sent=[]
    def control(self,strategy='trend',action='status',**kw):
        return auto.control(dict(market='KR',strategy=strategy,action=action,**kw),self.db,self.gate)
    def split(self):
        self.control(action='allocate',budget='250000')
        self.control('breakout','allocate',budget='250000')
        for strategy in ('trend','breakout'):
            self.control(strategy,'start',confirmed=True)
    def seed(self,strategy,positions=None):
        with auto.connect(self.db) as db:
            state=json.loads(db.execute("SELECT data FROM portfolios WHERE market='KR' AND strategy=?",(strategy,)).fetchone()[0])
            state['observed']={'KRX:005930':dict(day='20260930',volume=10,at=auto.stamp(NOW-dt.timedelta(seconds=60)))}
            if positions is not None:state['positions']=positions
            db.execute("UPDATE portfolios SET data=? WHERE market='KR' AND strategy=?",(json.dumps(state),strategy))
    def position(self,strategy,code='005930',qty=1,price=70000):
        return dict(code=code,exchange='KRX',name='synthetic',strategy=strategy,quantity=qty,entry_price=price,entry_fx=1,cost_krw=price*qty,entry_at=auto.stamp(NOW),last_price=price,last_at=auto.stamp(NOW),return_pct=0)
    def intent(self,strategy,status='accepted',side='buy',qty=10,applied=0,price=9000,code='005930',number='123'):
        p=dict(mode='real',market='KR',side=side,quantity=str(qty),price=str(price),code=code,exchange='KRX',name='synthetic')
        with auto.connect(self.db) as db:
            row=db.execute("INSERT INTO intents(market,strategy,dedup,payload,status,number,filled,applied,average,created,updated) VALUES('KR',?,?,?,?,?,?,?,?,?,?)",(strategy,strategy+side+code,json.dumps(p),status,number,applied,applied,str(price) if applied else None,auto.stamp(NOW),auto.stamp(NOW)))
            return row.lastrowid
    def run_cycle(self,strategy,holdings=None,reports=None,barrier=None,price=70000):
        def send(c,order):self.sent.append(order);return 'accepted','456'
        def screen(s):
            if barrier:barrier.wait(timeout=5)
            return dict(status='ready',date='20260929',stocks=[dict(code='005930',exchange='KRX',name='synthetic',reason='signal')])
        with patch.object(auto,'account',return_value=(holdings or {},holdings or {},set())),patch.object(auto,'can_buy',return_value=True),patch.object(auto,'send',side_effect=send),patch.object(auto,'order_rows',return_value=reports or []):
            auto.cycle('KR',self.db,self.gate,NOW,lambda mode:object(),screen,lambda code:dict(quote=dict(cur_prc=price,trde_qty=20)),strategy)
    def test_independent_start_stop_status_and_zero_allocation(self):
        self.split();self.control('breakout','stop')
        self.assertTrue(self.control()['enabled']);self.assertFalse(self.control('breakout')['enabled'])
        for strategy in ('pullback','reversion','momentum'):
            self.assertEqual(self.control(strategy)['budget'],'0')
            with self.assertRaisesRegex(ValueError,'invalid_auto_budget'):self.control(strategy,'start',confirmed=True)
    def test_all_five_strategies_control_independently(self):
        self.control(action='allocate',budget='0')
        for strategy in STRATEGIES:
            self.control(strategy,'allocate',budget='100000')
            self.control(strategy,'start',confirmed=True)
        for stopped in STRATEGIES:
            self.control(stopped,'stop')
            for other in STRATEGIES:
                self.assertEqual(self.control(other)['enabled'],STRATEGIES.index(other)>STRATEGIES.index(stopped))
        self.assertEqual(self.control()['market_budget']['allocated'],'500000')
    def test_default_worker_cycle_visits_all_enabled_strategies(self):
        self.control(action='allocate',budget='0')
        for strategy in STRATEGIES:
            self.control(strategy,'allocate',budget='100000');self.control(strategy,'start',confirmed=True)
        visited=[]
        def scan(strategy):visited.append(strategy);return dict(status='ready',date='20260929',stocks=[])
        with patch.object(auto,'account',return_value=({}, {}, set())),patch.object(auto,'send') as send:
            auto.cycle('KR',self.db,self.gate,NOW,lambda _:object(),scan,lambda _:self.fail('empty scan quote'))
            send.assert_not_called()
        self.assertCountEqual(visited,STRATEGIES);self.assertEqual(len(visited),5)
    def test_running_edit_revision_and_committed_floor(self):
        self.split();before=self.control()
        self.seed('trend',{'KRX:005930':self.position('trend',qty=2,price=9000)})
        self.intent('trend',status='partial',applied=2)
        with self.assertRaisesRegex(ValueError,'allocation_below_committed'):self.control(action='allocate',budget='90719')
        self.control(action='allocate',budget='90720')
        with auto.connect(self.db) as db:
            self.assertEqual(budgets.exposure(db,'KR','trend')[0],Decimal('90720'))
            self.assertGreater(db.execute("SELECT revision FROM portfolios WHERE market='KR' AND strategy='trend'").fetchone()[0],0)
        self.assertTrue(self.control()['enabled']);self.assertEqual(before['started_at'],self.control()['started_at'])
    def test_cap_is_atomic_under_concurrent_allocation(self):
        self.control(action='allocate',budget='0')
        def allocate(s):
            try:self.control(s,'allocate',budget='300000');return True
            except ValueError as error:self.assertEqual(str(error),'market_allocation_cap');return False
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            results=list(pool.map(allocate,('trend','breakout')))
        self.assertEqual(sum(results),1);self.assertEqual(self.control()['market_budget']['allocated'],'300000')
    def test_same_symbol_concurrent_strategies_only_one_order(self):
        self.split();self.seed('trend');self.seed('breakout');barrier=threading.Barrier(2)
        # Mocks apply across both threads for the entire race, not per-thread lifetimes.
        def screen(s):barrier.wait(timeout=5);return dict(status='ready',date='20260929',stocks=[dict(code='005930',exchange='KRX',name='synthetic',reason='signal')])
        def send(c,order):self.sent.append(order);return 'accepted','456'
        with patch.object(auto,'account',return_value=({}, {}, set())),patch.object(auto,'can_buy',return_value=True),patch.object(auto,'send',side_effect=send):
            with concurrent.futures.ThreadPoolExecutor(2) as pool:
                jobs=[pool.submit(auto.cycle,'KR',self.db,self.gate,NOW,lambda mode:object(),screen,lambda code:dict(quote=dict(cur_prc=70000,trde_qty=20)),s) for s in ('trend','breakout')]
                for job in jobs:job.result(timeout=10)
        self.assertEqual(len(self.sent),1)
        with auto.connect(self.db) as db:self.assertEqual(db.execute("SELECT count(*) FROM intents WHERE status='accepted'").fetchone()[0],1)
    def test_stopped_holdings_and_manual_account_holdings_block_buy(self):
        self.split();self.control('breakout','stop');self.seed('trend')
        self.seed('breakout',{'KRX:005930':self.position('breakout')})
        self.run_cycle('trend');self.assertEqual(self.sent,[])
        self.seed('breakout',{});self.seed('trend');self.run_cycle('trend',holdings={'005930':1});self.assertEqual(self.sent,[])
    def test_account_rows_do_not_overwrite_other_exchange_or_fractional_holdings(self):
        rows=[dict(stk_cd='SYNTH',poss_qty='2',sell_alowq='2'),dict(stk_cd='SYNTH',poss_qty='3',sell_alowq='1')]
        self.assertEqual(auto.account_totals(rows,'US','poss_qty','sell_alowq'),({'SYNTH':5},{'SYNTH':3}))
        rows[0]['poss_qty']='2.5'
        with self.assertRaisesRegex(RuntimeError,'account_schema'):auto.account_totals(rows,'US','poss_qty','sell_alowq')
    def test_stopped_pending_and_unknown_reserve_still_block(self):
        for status in budgets.PENDING:
            with self.subTest(status=status):
                with auto.connect(self.db) as db:db.execute('DELETE FROM intents')
                self.split();self.control('breakout','stop');self.seed('trend')
                self.intent('breakout',status=status,number='' if status=='unknown' else '123')
                self.run_cycle('trend');self.assertEqual(self.sent,[])
    def test_stale_proposal_after_running_allocation_edit_is_discarded(self):
        self.split();self.seed('trend')
        def screen(s):self.control(action='allocate',budget='240000');return dict(status='ready',date='20260929',stocks=[dict(code='005930',exchange='KRX',name='synthetic')])
        with patch.object(auto,'send') as send:
            auto.cycle('KR',self.db,self.gate,NOW,lambda mode:object(),screen,lambda code:dict(quote=dict(cur_prc=70000,trde_qty=20)),'trend')
            send.assert_not_called()
    def test_other_strategy_allocation_edit_invalidates_market_snapshot(self):
        self.split();self.seed('trend')
        def screen(s):self.control('breakout','allocate',budget='240000');return dict(status='ready',date='20260929',stocks=[dict(code='005930',exchange='KRX',name='synthetic')])
        with patch.object(auto,'send') as send:
            auto.cycle('KR',self.db,self.gate,NOW,lambda mode:object(),screen,lambda code:dict(quote=dict(cur_prc=70000,trde_qty=20)),'trend')
            send.assert_not_called()
        self.assertEqual(self.control()['budget'],'250000')
    def test_ten_positions_is_per_strategy(self):
        self.split()
        positions={'KRX:'+f'{i:06d}':self.position('breakout',f'{i:06d}',price=1000) for i in range(10)}
        self.seed('breakout',positions);self.control('breakout','stop');self.seed('trend')
        self.run_cycle('trend');self.assertEqual(len(self.sent),1)
    def test_own_ten_positions_prevent_eleventh_buy(self):
        self.split()
        positions={'KRX:'+f'{i:06d}':self.position('trend',f'{i:06d}',price=1000) for i in range(10)}
        self.seed('trend',positions)
        quotes=lambda code:dict(quote=dict(cur_prc=1000 if code!='005930' else 70000,trde_qty=20))
        scan=dict(status='ready',date='20260929',stocks=[dict(code='005930',exchange='KRX',name='synthetic')])
        with patch.object(auto,'account',return_value=({p['code']:1 for p in positions.values()},{p['code']:1 for p in positions.values()},set())),patch.object(auto,'send') as send:
            auto.cycle('KR',self.db,self.gate,NOW,lambda mode:object(),lambda _:scan,quotes,'trend')
            send.assert_not_called()
    def test_reconciled_fill_is_in_budget_before_next_buy(self):
        self.split();self.seed('trend');self.intent('trend',qty=1,price=200000,code='000001')
        self.run_cycle('trend',holdings={'000001':1},reports=[dict(ord_no='123',stk_cd='000001',cntr_qty='1',ord_remnq='0',cntr_uv='200000')])
        self.assertEqual(self.sent,[])
        self.assertEqual(self.control()['positions'][0]['quantity'],1)
    def test_partial_cancellation_reserves_broker_remaining_quantity(self):
        self.split();self.control('breakout','stop');self.intent('breakout')
        report=dict(ord_no='123',stk_cd='005930',cntr_qty='2',ord_remnq='3',cntr_uv='9000')
        with patch.object(auto,'order_rows',return_value=[report]),patch.object(auto,'account',return_value=({'005930':2},{'005930':2},set())):
            auto.cycle('KR',self.db,self.gate,NOW,lambda _:object(),strategy='breakout')
        self.control('breakout','allocate',budget='45270')
        with self.assertRaisesRegex(ValueError,'allocation_below_committed'):self.control('breakout','allocate',budget='45269')
        with auto.connect(self.db) as db:self.assertEqual(budgets.exposure(db,'KR','breakout')[0],Decimal('45270'))
    def test_partial_reconcile_updates_each_enabled_strategys_own_book(self):
        self.split();self.intent('trend');self.intent('breakout',qty=4,price=25000,code='000001',number='789')
        reports=[dict(ord_no='123',stk_cd='005930',cntr_qty='2',ord_remnq='8',cntr_uv='9000'),dict(ord_no='789',stk_cd='000001',cntr_qty='1',ord_remnq='3',cntr_uv='25000')]
        def quote(code):return dict(quote=dict(cur_prc=9000 if code=='005930' else 25000,trde_qty=20))
        with patch.object(auto,'account',return_value=({'005930':2,'000001':1},{'005930':2,'000001':1},set())),patch.object(auto,'order_rows',return_value=reports),patch.object(auto,'send') as send:
            auto.cycle('KR',self.db,self.gate,NOW,lambda _:object(),lambda _:dict(status='ready',date='20260929',stocks=[]),quote)
            send.assert_not_called()
        self.assertEqual([(p['code'],p['quantity']) for p in self.control()['positions']],[('005930',2)])
        self.assertEqual([(p['code'],p['quantity']) for p in self.control('breakout')['positions']],[('000001',1)])
        self.assertEqual(self.control()['orders'][0]['status'],'partial')
        self.assertEqual(self.control('breakout')['orders'][0]['status'],'partial')
    def test_unknown_other_symbol_blocks_all_new_buys(self):
        self.split();self.seed('trend');self.control('breakout','stop')
        self.intent('breakout',status='unknown',number='',code='000001')
        self.run_cycle('trend');self.assertEqual(self.sent,[])
        self.assertIn('시장 미확인',str(self.control()['issues']))
    def test_global_pause_reconciles_without_start_or_send(self):
        self.split();self.intent('trend',qty=1,price=70000)
        trading_control.status('pause',self.gate)
        report=dict(ord_no='123',stk_cd='005930',cntr_qty='1',ord_remnq='0',cntr_uv='70000')
        with patch.object(auto,'account',return_value=({'005930':1},{'005930':1},set())),patch.object(auto,'order_rows',return_value=[report]),patch.object(auto,'send') as send:
            auto.cycle('KR',self.db,self.gate,NOW,lambda mode:object(),lambda _:self.fail('scan while globally paused'),lambda _:self.fail('quote while globally paused'))
            send.assert_not_called()
        self.assertTrue(self.control()['enabled']);self.assertTrue(self.control('breakout')['enabled'])
        self.assertFalse(self.control()['global_enabled']);self.assertEqual(self.control()['positions'][0]['quantity'],1)
    def test_reconcile_stopped_partial_fill_no_scan_quote_or_send_even_global_pause(self):
        self.split();self.control('breakout','stop');self.intent('breakout')
        trading_control.status('pause',self.gate)
        report=dict(ord_no='123',stk_cd='005930',cntr_qty='2',ord_remnq='8',cntr_uv='9000')
        with patch.object(auto,'order_rows',return_value=[report]),patch.object(auto,'account',return_value=({'005930':2},{'005930':2},set())),patch.object(auto,'send') as send:
            auto.cycle('KR',self.db,self.gate,NOW,lambda mode:object(),lambda _:self.fail('scan after stop'),lambda _:self.fail('quote after stop'),'breakout')
            send.assert_not_called()
        result=self.control('breakout');self.assertFalse(result['enabled']);self.assertEqual(result['positions'][0]['quantity'],2)
        self.assertEqual(result['market_budget']['strategies'][0]['committed'],'90720.00')
        self.assertEqual(self.control()['positions'],[])
    def test_sell_only_selected_broker_confirmed_quantity(self):
        self.split();self.seed('trend',{'KRX:005930':self.position('trend',qty=2)})
        self.seed('breakout',{'KRX:000001':self.position('breakout','000001',qty=3)})
        self.run_cycle('trend',holdings={'005930':2,'000001':3},price=73500)
        self.assertEqual(len(self.sent),1);self.assertEqual(self.sent[0]['side'],'sell');self.assertEqual(self.sent[0]['quantity'],'2')
        self.assertEqual(self.control('breakout')['positions'][0]['quantity'],3)
    def test_selected_report_and_history_are_isolated(self):
        from auto_performance_history import record
        from real_profit_report import build
        self.intent('trend',status='filled',side='buy',qty=1,applied=1,price=100)
        self.intent('trend',status='filled',side='sell',qty=1,applied=1,price=110)
        self.intent('breakout',status='filled',side='buy',qty=1,applied=1,price=100,code='000001')
        self.intent('breakout',status='filled',side='sell',qty=1,applied=1,price=90,code='000001')
        with auto.connect(self.db) as db:
            record(db,NOW)
            self.assertEqual(build(db,'KR','trend')['summary']['pnl'],10)
            self.assertEqual(build(db,'KR','breakout')['summary']['pnl'],-10)
        self.assertEqual(self.control()['performance']['realized_pnl'],10)
        self.assertEqual(self.control('breakout')['performance']['realized_pnl'],-10)
        self.assertEqual([s['strategy'] for s in self.control()['performance_history']['series']],list(STRATEGIES))
        self.assertTrue(all(o['order']['code']=='005930' for o in self.control()['orders']))
    def test_five_strategy_chart_uses_each_portfolios_own_positions(self):
        from auto_performance_history import record
        self.split()
        trend=self.position('trend',code='000001',price=100);trend['last_price']=110
        breakout=self.position('breakout',code='000002',qty=2,price=100);breakout['last_price']=90
        self.seed('trend',{'KRX:000001':trend});self.seed('breakout',{'KRX:000002':breakout})
        self.intent('trend',status='filled',qty=1,applied=1,price=100,code='000001')
        self.intent('breakout',status='filled',qty=2,applied=2,price=100,code='000002')
        with auto.connect(self.db) as db:record(db,NOW)
        for selected in ('trend','breakout'):
            response=self.control(selected)
            history={s['strategy']:s['points'] for s in response['performance_history']['series']}
            self.assertEqual(len(history),5)
            self.assertEqual(history['trend'][0]['return_pct'],10)
            self.assertEqual(history['breakout'][0]['return_pct'],-10)
            self.assertIsNone(history['momentum'][0]['return_pct'])
            self.assertEqual(response['positions'][0]['strategy'],selected)

class MigrationTests(unittest.TestCase):
    def test_startup_refuses_legacy_without_offline_backup(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'legacy.db'
            with sqlite3.connect(path) as db:db.execute('CREATE TABLE portfolios(market TEXT PRIMARY KEY,strategy,enabled,revision,budget,started,data)')
            with self.assertRaisesRegex(ValueError,'offline_migration'):auto.connect(path)
            with sqlite3.connect(path) as db:self.assertEqual(db.execute("SELECT count(*) FROM sqlite_master WHERE name='market_budgets'").fetchone()[0],0)
    def test_legacy_byte_exact_rows_dedup_and_rollback(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'legacy.db';backup=Path(root)/'backup.db'
            state=initial(NOW);state['positions']={'KRX:005930':dict(strategy='breakout',quantity=9,entry_price=60000)};state['seen']={'unchanged':True}
            legacy=('KR','breakout',1,17,'2400000',auto.stamp(NOW),json.dumps(state))
            legacy_intent=(1,'KR','breakout','legacy-breakout-buy',json.dumps(dict(mode='real',market='KR',side='buy',quantity='10',price='60000',exchange='KRX',code='005930',name='synthetic')),'partial','999',9,'60000',9,auto.stamp(NOW),auto.stamp(NOW))
            with sqlite3.connect(path) as db:
                db.execute('CREATE TABLE portfolios(market TEXT PRIMARY KEY,strategy,enabled,revision,budget,started,data)')
                db.execute('INSERT INTO portfolios VALUES(?,?,?,?,?,?,?)',legacy)
                db.execute('INSERT INTO portfolios VALUES(?,?,?,?,?,?,?)',('US','momentum',0,4,'1200',None,json.dumps(initial(NOW))))
                db.execute('CREATE TABLE marker(value TEXT)');db.execute("INSERT INTO marker VALUES('dedup-synthetic')")
                db.execute('CREATE TABLE intents(id INTEGER PRIMARY KEY,market,strategy,dedup TEXT UNIQUE,payload,status,number,filled INTEGER DEFAULT 0,average,applied INTEGER DEFAULT 0,created,updated)')
                db.execute('INSERT INTO intents VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',legacy_intent)
            budgets.migrate_file(path,backup)
            with auto.connect(path) as db:
                self.assertEqual(tuple(db.execute("SELECT * FROM portfolios WHERE market='KR' AND strategy='breakout'").fetchone()),legacy)
                self.assertEqual(tuple(db.execute("SELECT * FROM portfolios_legacy_v1 WHERE market='KR'").fetchone()),legacy)
                self.assertEqual(db.execute("SELECT total_cap FROM market_budgets WHERE market='KR'").fetchone()[0],'2400000')
                self.assertEqual(db.execute("SELECT total_cap,currency FROM market_budgets WHERE market='US'").fetchone()[1],'USD')
                self.assertEqual(db.execute("SELECT sum(enabled),sum(CAST(budget AS INTEGER)) FROM portfolios WHERE market='KR' AND strategy<>'breakout'").fetchone()[0],0)
                self.assertEqual(db.execute("SELECT sum(CAST(budget AS INTEGER)) FROM portfolios WHERE market='KR' AND strategy<>'breakout'").fetchone()[0],0)
                self.assertEqual(db.execute('SELECT value FROM marker').fetchone()[0],'dedup-synthetic')
                migrated_intent=tuple(db.execute('SELECT * FROM intents').fetchone())
                self.assertEqual(migrated_intent[:-1],legacy_intent);self.assertIsNone(migrated_intent[-1])
                self.assertEqual(budgets.exposure(db,'KR','breakout')[0],Decimal('600600'))
            self.assertEqual(backup.stat().st_mode & 0o777,0o600)
            budgets.restore_file(path,backup)
            with sqlite3.connect(path) as db:
                self.assertEqual(db.execute("SELECT * FROM portfolios WHERE market='KR'").fetchone(),legacy)
                self.assertEqual(db.execute("SELECT count(*) FROM sqlite_master WHERE name='market_budgets'").fetchone()[0],0)
                self.assertEqual(db.execute('SELECT * FROM intents').fetchone(),legacy_intent)
    def test_rollback_refuses_wal_sidecars(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'live.db';path.touch();Path(str(path)+'-wal').touch();(Path(root)/'backup').touch()
            with self.assertRaisesRegex(ValueError,'offline_clean'):budgets.restore_file(path,Path(root)/'backup')

if __name__=='__main__':unittest.main()
