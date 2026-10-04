"""Offline portfolio prototype. No brokerage order endpoints exist in this app."""
import argparse
import datetime as dt
import getpass
import json
import math
import random
import urllib.request
from pathlib import Path

ASSETS = ('KR', 'US', 'GOLD')
INITIAL = 1_000_000
WEEKLY = 100_000
FEE = 0.002  # Illustrative all-in execution cost, not broker pricing.


def targets(history):
    """Use only completed prior weekly observations, 26/52 week momentum."""
    if len(history) < 53:
        raise ValueError('최소 53개 과거 주간 관측값이 필요합니다.')
    strength = {}
    for asset in ('KR', 'US'):
        prices = [r[asset] for r in history]
        trend = prices[-1] > sum(prices[-40:]) / 40
        score = (prices[-1] / prices[-27] - 1 + prices[-1] / prices[-53] - 1) / 2
        if trend and score > 0:
            strength[asset] = score
    weights = {'KR': 0.0, 'US': 0.0, 'GOLD': 0.15}
    if len(strength) == 2:
        winner = max(strength, key=strength.get)
        weights.update({k: 0.45 if k == winner else 0.25 for k in strength})
    elif strength:
        weights[next(iter(strength))] = 0.50
    return weights  # Residual is cash; no leverage or short selling.


class Portfolio:
    def __init__(self):
        self.cash = 0.0
        self.qty = dict.fromkeys(ASSETS, 0)
        self.units = 0.0
        self.deposits = 0.0
        self.peak = 1.0
        self.halted = False

    def value(self, prices):
        return self.cash + sum(self.qty[a] * prices[a] for a in ASSETS)

    def nav(self, prices):
        return self.value(prices) / self.units if self.units else 1.0

    def deposit(self, amount, prices):
        if amount <= 0 or not math.isfinite(amount):
            raise ValueError('입금액은 양수여야 합니다.')
        nav = self.nav(prices)
        if nav <= 0:
            raise ValueError('자산가치가 0 이하입니다.')
        self.units += amount / nav
        self.cash += amount
        self.deposits += amount

    def drawdown(self, prices):
        nav = self.nav(prices)
        self.peak = max(self.peak, nav)
        return 1 - nav / self.peak

    def trade(self, prices, weights, rebalance=False):
        if set(prices) != set(ASSETS) or any(p <= 0 or not math.isfinite(p) for p in prices.values()):
            raise ValueError('유효한 원화 환산 가격이 필요합니다.')
        if set(weights) != set(ASSETS) or any(w < 0 or not math.isfinite(w) for w in weights.values()) or sum(weights.values()) > 1:
            raise ValueError('비중 합계는 0~1이어야 합니다.')
        if self.halted:
            return []
        total = self.value(prices)
        desired = {a: int(total * weights[a] / prices[a]) for a in ASSETS}
        orders = []
        if rebalance:
            for a in ASSETS:
                # Sell on monthly signal changes only; 5 percentage point tolerance.
                if self.qty[a] * prices[a] > total * (weights[a] + 0.05):
                    n = self.qty[a] - desired[a]
                    self.qty[a] -= n
                    self.cash += n * prices[a] * (1 - FEE)
                    orders.append({'asset': a, 'side': 'SELL', 'qty': n})
        reserve = total * (1 - sum(weights.values()))
        deficits = sorted(ASSETS, key=lambda a: total * weights[a] - self.qty[a] * prices[a], reverse=True)
        for a in deficits:
            affordable = max(0, int((self.cash - reserve) / (prices[a] * (1 + FEE))))
            n = min(max(0, desired[a] - self.qty[a]), affordable)
            if n:
                self.cash -= n * prices[a] * (1 + FEE)
                self.qty[a] += n
                orders.append({'asset': a, 'side': 'BUY', 'qty': n})
        return orders


def synthetic_data():
    rng = random.Random(21)
    prices = {'KR': 35000.0, 'US': 80000.0, 'GOLD': 180000.0}
    rows = []
    for i in range(105):
        for a in ASSETS:
            drift = -0.012 if 68 <= i < 83 and a != 'GOLD' else 0.003
            prices[a] *= math.exp(drift + rng.gauss(0, 0.023 if a != 'GOLD' else 0.015))
        rows.append({'date': str(dt.date(2024, 1, 5) + dt.timedelta(weeks=i)), **prices})
    return rows


def simulate(rows):
    if len(rows) < 54:
        raise ValueError('최소 54주 데이터가 필요합니다.')
    dates = [dt.date.fromisoformat(r['date']) for r in rows]
    if any(b <= a for a, b in zip(dates, dates[1:])):
        raise ValueError('날짜는 중복 없이 오름차순이어야 합니다.')
    if any((b-a).days != 7 for a, b in zip(dates, dates[1:])):
        raise ValueError('이 시제품은 7일 간격의 주간 관측값만 지원합니다.')
    for r in rows:
        if any(not isinstance(r.get(a), (int, float)) or not math.isfinite(r[a]) or r[a] <= 0 for a in ASSETS):
            raise ValueError('모든 자산의 가격은 유효한 양수여야 합니다.')
    p = Portfolio()
    records = []
    month = None
    allocation = None
    for i in range(53, len(rows)):
        row = rows[i]
        prices = {a: row[a] for a in ASSETS}
        dd = p.drawdown(prices)
        if dd >= 0.30:
            p.halted = True  # Latched pause; not a guaranteed loss cap or liquidation.
        new_month = row['date'][:7] != month
        if new_month:
            allocation = targets(rows[:i])
            month = row['date'][:7]
        p.deposit(INITIAL + WEEKLY if i == 53 else WEEKLY, prices)
        orders = p.trade(prices, allocation, new_month)
        dd = p.drawdown(prices)
        if dd >= 0.30:
            p.halted = True
        records.append({'date': row['date'], 'deposits': p.deposits,
                        'value': round(p.value(prices), 2), 'cash': round(p.cash, 2),
                        'holdings': dict(p.qty), 'target': dict(allocation),
                        'unit_return': p.nav(prices) - 1, 'drawdown': dd,
                        'halted': p.halted, 'orders': orders})
    return {'mode': 'OFFLINE_SIMULATION', 'broker_connected': False,
            'records': records, 'max_observed_drawdown': max(r['drawdown'] for r in records)}


def check_mock_auth():
    key = getpass.getpass('키움 모의투자 App Key (표시/저장 안 함): ')
    secret = getpass.getpass('키움 모의투자 App Secret (표시/저장 안 함): ')
    if not key or not secret:
        raise ValueError('키가 비어 있습니다.')
    body = json.dumps({'grant_type': 'client_credentials', 'appkey': key, 'secretkey': secret}).encode()
    req = urllib.request.Request('https://mockapi.kiwoom.com/oauth2/token', data=body,
                                 headers={'Content-Type': 'application/json;charset=UTF-8'})
    with urllib.request.urlopen(req, timeout=15) as response:
        result = json.load(response)
    if str(result.get('return_code')) != '0' or not result.get('token'):
        raise ValueError('모의 인증 실패. API 신청·허용 IP·키 종류를 확인하세요.')
    print('모의 서버 인증 성공. 토큰은 저장하지 않았으며 주문은 전송하지 않았습니다.')


def main():
    parser = argparse.ArgumentParser(description='키움 연동 준비용 오프라인 투자 시제품')
    parser.add_argument('command', choices=['demo', 'simulate', 'check-mock-auth'])
    parser.add_argument('--input', type=Path)
    parser.add_argument('--output', type=Path, default=Path('report.json'))
    args = parser.parse_args()
    try:
        if args.command == 'check-mock-auth':
            check_mock_auth()
            return
        if args.command == 'simulate' and args.input is None:
            parser.error('simulate에는 --input 경로가 필요합니다.')
        rows = synthetic_data() if args.command == 'demo' else json.loads(args.input.read_text())
        report = simulate(rows)
        report['data_source'] = 'SYNTHETIC_NOT_REAL_MARKET_DATA' if args.command == 'demo' else 'USER_SUPPLIED_UNVERIFIED'
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print('오프라인 시뮬레이션 완료. 실주문 없음. 결과:', args.output)
        print('실제 시장 성과 검증이 아닙니다.' if args.command == 'demo' else '입력 데이터의 환율·배당·분할 보정은 별도 검증이 필요합니다.')
    except Exception as exc:
        # Never print broker response bodies or credentials.
        if args.command == 'check-mock-auth':
            parser.exit(1, '모의 인증 실패: 연결·허용 IP·모의 키 설정을 확인하세요.\n')
        parser.exit(1, '실행 실패: ' + str(exc) + '\n')


if __name__ == '__main__':
    main()
