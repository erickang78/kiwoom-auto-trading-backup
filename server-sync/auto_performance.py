"""Read-only cumulative statistics from confirmed automatic fills; costs excluded."""
import json
from decimal import Decimal

def cumulative(db, market, strategy, positions):
    buys = Decimal(0); realized = Decimal(0); closed = wins = 0; held = {}
    rows = db.execute('SELECT * FROM intents WHERE market=? AND strategy=? ORDER BY id', (market,strategy)).fetchall()
    try:
        for r in rows:
            if r['status'] in ('unknown','reconcile_error'):
                raise ValueError('주문 체결 확인이 필요합니다.')
            qty = r['applied']
            if qty != r['filled']:
                raise ValueError('체결 수량 확인이 필요합니다.')
            if not qty:
                continue
            p = json.loads(r['payload']); price = Decimal(r['average']); key = p['exchange']+':'+p['code']
            if qty < 1 or qty > int(p.get('quantity', 1)) or not price.is_finite() or price <= 0:
                raise ValueError('체결 가격 확인이 필요합니다.')
            if p['side'] == 'buy':
                if key in held: raise ValueError('중복 매수 기록 확인이 필요합니다.')
                held[key] = dict(price=price, quantity=qty, pnl=Decimal(0)); buys += price*qty
            elif p['side'] == 'sell':
                lot=held[key]
                if qty > lot['quantity']: raise ValueError('매도 수량 확인이 필요합니다.')
                pnl = (price-lot['price'])*qty; realized += pnl; lot['pnl'] += pnl; lot['quantity'] -= qty
                if not lot['quantity']:
                    closed += 1; wins += int(lot['pnl'] > 0); del held[key]
            else: raise ValueError('매매 방향 확인이 필요합니다.')
        current = {p['exchange']+':'+p['code']:p for p in positions if p['strategy']==strategy}
        if set(current) != set(held): raise ValueError('보유·체결 기록 대조가 필요합니다.')
        unrealized = Decimal(0)
        for key, entry in held.items():
            p=current[key]; last=Decimal(str(p['last_price']))
            if p['quantity']!=entry['quantity'] or not last.is_finite() or last<=0 or Decimal(str(p['entry_price']))!=entry['price']:
                raise ValueError('보유 평가 가격 확인이 필요합니다.')
            unrealized += (last-entry['price'])*entry['quantity']
        total = realized+unrealized
        return dict(available=True,costs_included=False,cumulative_buy_amount=float(buys),realized_pnl=float(realized),unrealized_pnl=float(unrealized),total_pnl=float(total),return_pct=float(total/buys*100) if buys else None,win_rate_pct=wins/closed*100 if closed else None,closed_trades=closed)
    except (ValueError,KeyError,TypeError,ArithmeticError):
        return dict(available=False,costs_included=False,reason='실제 체결·보유 기록을 확인한 뒤 성과를 계산합니다.')
