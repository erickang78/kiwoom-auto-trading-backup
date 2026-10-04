import json, sqlite3, unittest
from virtual_profit_report import build

class VirtualProfitTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row
        self.db.execute('CREATE TABLE events(id INTEGER PRIMARY KEY,data TEXT,portfolio INTEGER)')
    def add(self,pid=6,**changes):
        e=dict(kind='SELL',at='2025-12-31T15:01:00+00:00',entry_price=100,reference_price=110,quantity=2)
        e.update(changes);self.db.execute('INSERT INTO events(data,portfolio) VALUES(?,?)',(json.dumps(e),pid))
    def test_weighted_periods_and_filters(self):
        self.add();self.add(7,entry_price=200,reference_price=190)
        self.add(1,reference_price=999);self.add(kind='BUY',reference_price=999)
        r=build(self.db,'KR');self.assertEqual(r['summary']['pnl'],0)
        self.assertEqual(r['daily'][0]['period'],'2026-01-01')
        self.assertEqual(r['yearly'][0]['period'],'2026')
        self.assertEqual(r['monthly'][0]['cost'],600)
        self.assertEqual(build(self.db,'KR','trend')['summary']['return_pct'],10)
        self.assertEqual(build(self.db,'US')['summary']['sell_orders'],1)
    def test_invalid_does_not_show_partial_total(self):
        self.add();self.add(entry_price='NaN')
        r=build(self.db,'KR');self.assertFalse(r['available']);self.assertIsNone(r['summary']);self.assertEqual(r['daily'],[])
    def test_empty_and_legacy(self):
        self.assertEqual(build(self.db,'KR')['summary']['sell_orders'],0)
        self.add(1,entry_usd=50,reference_usd=60)
        self.assertEqual(build(self.db,'US')['summary']['return_pct'],20)

if __name__=='__main__': unittest.main()
