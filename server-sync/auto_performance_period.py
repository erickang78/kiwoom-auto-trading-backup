"""Read-only calendar-period performance from confirmed cumulative snapshots."""
import datetime as dt
import json
import math
from zoneinfo import ZoneInfo
from auto_performance import cumulative
DAYS=(3,5,10,30,50,100)
KST=ZoneInfo('Asia/Seoul')
def number(value):
    value=float(value)
    if not math.isfinite(value): raise ValueError('non-finite performance')
    return value
def calculate(current,base,days,start,end):
    meta=dict(days=days,period_start=start.isoformat(),period_end=end.isoformat(),costs_included=False,basis='period')
    try:
        if not current.get('available') or not base.get('available'): raise ValueError('현재 또는 기간 시작 전 평가 기록을 확인할 수 없습니다.')
        opening=number(base['holding_cost'])+number(base['unrealized_pnl'])
        buys=number(current['cumulative_buy_amount'])-number(base['cumulative_buy_amount'])
        realized=number(current['realized_pnl'])-number(base['realized_pnl'])
        unrealized=number(current['unrealized_pnl'])-number(base['unrealized_pnl'])
        closed=int(current['closed_trades'])-int(base['closed_trades'])
        def wins(p): return int(p.get('winning_trades',round(number(p.get('win_rate_pct') or 0)*int(p['closed_trades'])/100)))
        won=wins(current)-wins(base)
        if min(opening,buys,closed,won)<-0.000001 or won>closed: raise ValueError('기간 전후 기록이 일치하지 않습니다.')
        capital=opening+buys; total=realized+unrealized
        return dict(meta,available=True,opening_value=opening,capital_base=capital,cumulative_buy_amount=buys,realized_pnl=realized,unrealized_pnl=unrealized,total_pnl=total,return_pct=total/capital*100 if capital>0 else None,closed_trades=closed,win_rate_pct=won/closed*100 if closed else None)
    except (KeyError,ValueError,TypeError,ArithmeticError) as exc:
        return dict(meta,available=False,reason='기간 손익을 계산할 과거 기록이 부족하거나 일치하지 않습니다. 누적 조회를 이용해 주세요.')
def periods(db,market,strategy,positions,now=None):
    now=now or dt.datetime.now(dt.timezone.utc)
    now=now.astimezone(KST)
    current=cumulative(db,market,strategy,positions)
    filled=db.execute('SELECT created FROM intents WHERE market=? AND strategy=? AND applied>0',(market,strategy)).fetchall()
    result={}
    for days in DAYS:
        start=dt.datetime.combine(now.date()-dt.timedelta(days=days-1),dt.time.min,tzinfo=KST)
        zero=dict(available=True,holding_cost=0,cumulative_buy_amount=0,realized_pnl=0,unrealized_pnl=0,closed_trades=0,winning_trades=0)
        try:
            prior=any(dt.datetime.fromisoformat(r['created']).astimezone(KST)<start for r in filled)
            if not prior:
                base=zero
            else:
                row=db.execute('SELECT at,data FROM daily_returns WHERE market=? AND strategy=? AND day<? ORDER BY day DESC LIMIT 1',(market,strategy,start.date().isoformat())).fetchone()
                base=json.loads(row['data']) if row else dict(available=False)
                if base.get('cumulative_buy_amount')==0: base=dict(base,holding_cost=0)
            result[str(days)]=calculate(current,base,days,start,now)
        except (ValueError,TypeError,KeyError):
            result[str(days)]=dict(available=False,days=days,reason='기간 시작 기록을 확인할 수 없습니다.')
    return result
