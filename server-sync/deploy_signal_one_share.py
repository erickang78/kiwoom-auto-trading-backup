from pathlib import Path
from datetime import datetime
import py_compile

def deploy(root,html):
 worker=root/'signal_validation.py'
 old=worker.read_text();new=old
 for a,b in [('from decimal import Decimal, ROUND_FLOOR', 'from decimal import Decimal'), ("'budget_krw': 100000", "'quantity': 1"), ("        quantity = int((Decimal(RULES['budget_krw']) / Decimal(str(price)) /\n                        Decimal(str(fx))).to_integral_value(rounding=ROUND_FLOOR))\n        if quantity < 1:\n            state['seen'][signal_key] = today\n            events.append(dict(stock, kind='SKIP', at=stamp(now), reference_usd=price,\n                               fx_rate=fx, reason='1주 가격이 10만 원 초과', quantity=0))\n            continue\n", "        quantity = RULES['quantity']\n")]:
  assert new.count(a)==1,a
  new=new.replace(a,b,1)
 original=html.read_text();tag='<script id="signal-validation-module">';a=original.index(tag)+len(tag);b=original.index("</script>",a);ui=original[a:b]
 for x,y in [('종목당 10만 원 · 최대 5종목', '신호 포착 시 종목당 1주 · 최대 5종목'), ('정수 수량만 계산하며 1주가 10만 원을 넘으면 제외합니다.', '매수 금액 제한 없이 조건에 포착된 종목을 1주씩 가상 매수합니다.')]:
  assert ui.count(x)==1,x
  ui=ui.replace(x,y,1)
 updated=original[:a]+ui+original[b:]
 stamp=datetime.now().strftime('%Y%m%d%H%M%S')
 for path,previous,content in [(worker,old,new),(html,original,updated)]:
  path.with_name(path.name+'.before-one-share-'+stamp).write_text(previous)
  temp=path.with_name(path.name+'.one-share-new');temp.write_text(content);temp.chmod(path.stat().st_mode & 0o777)
  if path==worker:compile(content,str(path),'exec')
  temp.replace(path)
 print('ONE_SHARE_UPDATED',stamp)

if __name__=='__main__':
 import sys
 deploy(Path(sys.argv[1]),Path(sys.argv[2]))
