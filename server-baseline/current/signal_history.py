"""Daily cumulative paper returns from recorded marks, never interpolated prices."""
import datetime as dt
import json
import math
from zoneinfo import ZoneInfo
STRATEGIES=('trend','breakout','pullback','reversion','momentum')
KST=ZoneInfo('Asia/Seoul')
def history(db,market,now):
    from signal_validation import upgrade
    series=[]
    for index,strategy in enumerate(STRATEGIES):
        pid=1+index+(5 if market=='KR' else 0)
        sales=[upgrade(r[0]) for r in db.execute('SELECT data FROM events WHERE portfolio=?',(pid,))]
        valid_sales=[];invalid_sales=False
        for e in sales:
            if e.get('kind')!='SELL':continue
            try:valid_sales.append((dt.datetime.fromisoformat(e['at']),e))
            except (KeyError,ValueError,TypeError):invalid_sales=True
        sales=valid_sales
        points=[]
        for day,at,raw in db.execute('SELECT day,at,data FROM daily_marks WHERE portfolio=? ORDER BY day',(pid,)):
            try:cutoff=dt.datetime.fromisoformat(at)
            except (ValueError,TypeError):continue
            if cutoff>now:continue
            positions=list(json.loads(raw).values())
            closed=[e for when,e in sales if when<=cutoff]
            try:
                if invalid_sales:raise ValueError('incomplete_history')
                cost=sum(p['entry_price']*p['quantity'] for p in closed+positions)
                pnl=sum(e['pnl'] for e in closed)+sum((p['last_price']-p['entry_price'])*p['quantity'] for p in positions)
                value=pnl/cost*100 if cost else None
                if value is not None and not math.isfinite(value):value=None
            except (KeyError,TypeError,ValueError,ZeroDivisionError):value=None
            points.append(dict(day=day,at=at,return_pct=value))
        series.append(dict(strategy=strategy,points=points))
    return dict(market=market,timezone='Asia/Seoul',basis='cumulative',costs_included=False,series=series)
