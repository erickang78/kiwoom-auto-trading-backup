"""Read-only calendar-period performance from confirmed cumulative snapshots."""
import datetime as dt
import json
import math
from zoneinfo import ZoneInfo
from auto_performance import cumulative
DAYS=(1,3,5,10,30,50,100)
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

def apply_costs(gross, rows, records, start, cost_error=None):
    """Period costs are incurred within the window, not old opening-lot costs."""
    from decimal import Decimal
    from auto_performance_net import confirmed_cost
    result=dict(gross,provisional=True,confirmed_costs_included=True,cost_error=cost_error,
                denominator_basis='opening_market_value_plus_period_gross_buys')
    if not gross.get('available'): return result
    held={}; realized_cost=Decimal(0); remaining_cost=Decimal(0); fees=taxes=Decimal(0); pending=confirmed=filled=0
    try:
        for row in sorted(rows,key=lambda r:r['id']):
            if row['status'] in ('unknown','reconcile_error') or row['filled']!=row['applied']: raise ValueError('ledger')
            qty=row['applied']
            if not qty: continue
            p=json.loads(row['payload']);key=(p['exchange'],p['code'])
            stamp=dt.datetime.fromisoformat(row['updated']);created=dt.datetime.fromisoformat(row['created'])
            if stamp.tzinfo is None or created.tzinfo is None: raise ValueError('timestamp')
            # Daily snapshots do not retain partial-fill cost observations. Never guess across the boundary.
            if created<start<=stamp: raise ValueError('boundary')
            in_period=stamp>=start
            expense=confirmed_cost(row,p,records) if in_period and not cost_error else None
            fee,tax=expense[:2] if expense else (Decimal(0),Decimal(0));cost=fee+tax
            if in_period:
                filled+=1;pending+=int(expense is None or not expense[2]);confirmed+=int(expense is not None);fees+=fee;taxes+=tax
            if p['side']=='buy':
                if key in held: raise ValueError('overlap')
                held[key]=[qty,cost]
            elif p['side']=='sell':
                lot=held[key]
                if qty>lot[0]: raise ValueError('quantity')
                allocated=lot[1]*Decimal(qty)/Decimal(lot[0]);realized_cost+=allocated+cost;lot[0]-=qty;lot[1]-=allocated
                if not lot[0]:del held[key]
            else:raise ValueError('side')
        remaining_cost=sum((v[1] for v in held.values()),Decimal(0))
        total_cost=fees+taxes
        assert abs(realized_cost+remaining_cost-total_cost)<Decimal('0.000001')
        realized=gross['realized_pnl']-float(realized_cost);unrealized=gross['unrealized_pnl']-float(remaining_cost);total=realized+unrealized
        result.update(available=True,costs_included=not pending,provisional=bool(pending),confirmed_fee=float(fees),confirmed_tax=float(taxes),pending_cost_orders=pending,confirmed_cost_orders=confirmed,filled_orders=filled,gross_total_pnl=gross['total_pnl'],realized_pnl=realized,unrealized_pnl=unrealized,total_pnl=total,return_pct=total/gross['capital_base']*100 if gross['capital_base']>0 else None,win_rate_pct=None,win_rate_basis='not_available_for_period_mark_to_market')
        return result
    except (ValueError,KeyError,TypeError,ArithmeticError,AssertionError):
        return dict(result,available=False,reason='기간 경계를 넘는 체결 또는 과거 기록을 정확히 나눌 수 없어 순성과를 표시하지 않습니다. 누적 조회를 이용해 주세요.')

def net_periods(db,market,strategy,positions,now=None):
    from auto_performance_net import read_costs
    now=(now or dt.datetime.now(dt.timezone.utc)).astimezone(KST)
    gross=periods(db,market,strategy,positions,now)
    rows=[dict(r) for r in db.execute('SELECT * FROM intents WHERE market=? AND strategy=? ORDER BY id',(market,strategy))]
    records,error=read_costs()
    result={}
    for days in DAYS:
        start=dt.datetime.combine(now.date()-dt.timedelta(days=days-1),dt.time.min,tzinfo=KST)
        item=apply_costs(gross[str(days)],rows,records,start,error)
        try:
            prior=any(dt.datetime.fromisoformat(r['created'])<start and r['applied']>0 for r in rows)
            if prior and item.get('available'):
                base=db.execute('SELECT at FROM daily_returns WHERE market=? AND strategy=? AND day<? ORDER BY day DESC LIMIT 1',(market,strategy,start.date().isoformat())).fetchone()
                at=dt.datetime.fromisoformat(base['at'])
                if at.tzinfo is None or any(at<dt.datetime.fromisoformat(r['updated'])<start and r['applied']>0 for r in rows):
                    raise ValueError('snapshot_gap')
        except (ValueError,TypeError,KeyError):
            item=dict(item,available=False,reason='기초 평가 기록 이후 기간 시작 전 체결을 정확히 나눌 수 없습니다. 누적 조회를 이용해 주세요.')
        result[str(days)]=item
    return result
