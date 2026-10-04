"""Record real strategy returns without broker calls or trading state mutations."""
import datetime as dt
import json,sqlite3,time
from pathlib import Path
from zoneinfo import ZoneInfo
from auto_performance import cumulative
STRATEGIES=('trend','breakout','pullback','reversion','momentum')
DB=Path('/opt/kiwoom/state/auto-trading.sqlite3')
def record(db,now):
    db.execute('CREATE TABLE IF NOT EXISTS daily_returns (market TEXT,strategy TEXT,day TEXT,at TEXT,data TEXT,PRIMARY KEY(market,strategy,day))')
    day=now.astimezone(ZoneInfo('Asia/Seoul')).date().isoformat()
    for market in ('KR','US'):
        row=db.execute('SELECT data FROM portfolios WHERE market=?',(market,)).fetchone()
        positions=list(json.loads(row['data'])['positions'].values()) if row else []
        for strategy in STRATEGIES:
            perf=cumulative(db,market,strategy,positions)
            db.execute('INSERT OR REPLACE INTO daily_returns VALUES(?,?,?,?,?)',(market,strategy,day,now.isoformat(),json.dumps(perf,allow_nan=False)))
def history(db,market):
    series=[]
    for strategy in STRATEGIES:
        points=[]
        for r in db.execute('SELECT day,at,data FROM daily_returns WHERE market=? AND strategy=? ORDER BY day',(market,strategy)):
            data=json.loads(r['data']);points.append(dict(day=r['day'],at=r['at'],return_pct=data.get('return_pct') if data.get('available') else None))
        series.append(dict(strategy=strategy,points=points))
    return dict(market=market,timezone='Asia/Seoul',basis='cumulative',costs_included=False,series=series)
def snapshot(path=DB,now=None):
    db=sqlite3.connect(path,timeout=5)
    try:
        with db:
            db.row_factory=sqlite3.Row;db.execute('BEGIN IMMEDIATE');record(db,now or dt.datetime.now(dt.timezone.utc))
    finally:db.close()
def worker():
    while True:
        try:snapshot()
        except Exception:print('real_performance_snapshot_failed',flush=True)
        time.sleep(60)
if __name__=='__main__':worker()
