#!/usr/bin/env python3
import datetime as dt
import json
import os
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen

OUT = Path('/opt/kiwoom/current/stock-list.json')
KIND_URL = 'https://kind.krx.co.kr/corpgeneral/corpList.do?method=download&searchType=13'

class TableParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.rows=[]; self.row=None; self.cell=None
    def handle_starttag(self, tag, attrs):
        if tag == 'tr': self.row=[]
        elif tag in ('td','th') and self.row is not None: self.cell=[]
    def handle_data(self, data):
        if self.cell is not None: self.cell.append(data)
    def handle_endtag(self, tag):
        if tag in ('td','th') and self.cell is not None:
            self.row.append(' '.join(''.join(self.cell).split())); self.cell=None
        elif tag == 'tr' and self.row is not None:
            if self.row: self.rows.append(self.row)
            self.row=None

def is_market_day(day):
    if day.weekday() >= 5 or (day.month, day.day) == (5, 1): return False
    last = dt.date(day.year, 12, 31)
    while last.weekday() >= 5: last -= dt.timedelta(days=1)
    if day == last: return False
    try:
        url=f'https://date.nager.at/api/v3/PublicHolidays/{day.year}/KR'
        holidays=json.load(urlopen(Request(url,headers={'User-Agent':'moa-stock-list/1'}),timeout=15))
        if day.isoformat() in {x['date'] for x in holidays}: return False
    except Exception as e:
        print(f'holiday lookup failed; skip safely: {e}')
        return False
    return True

def main():
    today=dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date()
    if not is_market_day(today):
        print(f'{today} is not a KRX market day; skipped'); return
    import broker_read as broker
    from credentials import load_credentials, REAL_PATH
    if not REAL_PATH.exists():
        raise RuntimeError('Stored real read-only credentials are required')
    broker.PATHS['ka10099'] = '/api/dostk/stkinfo'
    client = broker.Client(broker.REAL_BASE)
    client.authenticate(*load_credentials(REAL_PATH))
    stocks = {}
    for market in ('0', '10', '50'):
        market_count = 0
        for page in client.pages('ka10099', {'mrkt_tp': market}):
            rows = page.get('list')
            if not isinstance(rows, list):
                raise RuntimeError('Missing stock list in API response')
            for row in rows:
                code, name = str(row.get('code', '')), str(row.get('name', '')).strip()
                if len(code) == 6 and code.isascii() and code.isdigit() and name:
                    if code in stocks and stocks[code] != name:
                        raise RuntimeError('Conflicting stock names')
                    stocks[code] = name
                    market_count += 1
        if market_count < (50 if market == '50' else 500):
            raise RuntimeError('Incomplete market stock list: ' + market)
    if len(stocks) < 2000: raise RuntimeError(f'unexpected stock count: {len(stocks)}')
    payload={'updated_at':today.isoformat(),'source':'Kiwoom ka10099','count':len(stocks),'stocks':sorted(stocks.items())}
    tmp=OUT.with_suffix('.json.tmp'); tmp.write_text(json.dumps(payload,ensure_ascii=False,separators=(',',':'))+'\n'); os.replace(tmp,OUT)
    print(f'{today} updated {len(stocks)} stocks')
if __name__ == '__main__': main()
