"""Narrow origin-label deployment; preserves portfolio and trade databases."""
from pathlib import Path
import datetime
import hashlib
import json
import re
import shutil
import subprocess
import sys


def once(s, old, new):
    assert s.count(old) == 1, 'Origin patch anchor mismatch: '+old[:80]
    return s.replace(old, new)


def deploy(payload):
    root=Path('/opt/kiwoom/current')
    html=Path('/opt/kiwoom/dashboard-source/dist/index.html')
    changes={}
    p=root/'trading_api.py';s=p.read_text()
    changes[p]=once(s,'price=price, exchange=exchange)', 'price=price, exchange=exchange, trading_source="manual")')
    p=root/'auto_trading.py';s=p.read_text()
    changes[p]=once(once(s,"                order.pop('dedup', None)","                order['trading_source'] = 'automatic'\n                order['order']['trading_source'] = 'automatic'\n                order.pop('dedup', None)"),"                        order['name'] = event['name']","                        order['trading_source'] = 'automatic'\n                        order['name'] = event['name']")
    p=root/'refresh_api.py';s=p.read_text()
    changes[p]=once(s,'    def _json(self, status, body):\n','    def _json(self, status, body):\n        from trade_sources import annotate_snapshot\n        body = annotate_snapshot(body)\n')
    s=html.read_text()
    s=once(s,"line.textContent=(item.order.side", "line.textContent='[자동매매] '+(item.order.side")
    s=once(s,"['매매 구분','지정가 '+sn]", "['매매 구분','수동매매 · 지정가 '+sn]")
    s=once(s,'주문 접수 · 주문번호','[수동매매] 주문 접수 · 주문번호')
    s=once(s,'function renderOrders(card,executions,pending)',payload['tag_function']+'\nfunction renderOrders(card,executions,pending)')
    anchor="+kind+'</span></div>"
    assert s.count(anchor)==3
    s=s.replace(anchor,"+kind+'</span>'+tradeSourceTag(x)+'</div>")
    s=once(s,'</head>',payload['css']+'</head>')
    changes[html]=s
    for name,content in payload['files'].items():changes[root/name]=content
    for p,s in changes.items():
        if p.suffix=='.py':compile(s,str(p),'exec')
    suffix='.before-trade-tags-'+datetime.datetime.now().strftime('%Y%m%d%H%M%S')
    originals={p:p.read_bytes() if p.exists() else None for p in changes}
    for p in changes:
        if p.exists():shutil.copy2(p, str(p)+suffix)
    # Pause the existing worker only while replacing code; enabled/revision/DB remain untouched.
    active=subprocess.run(['systemctl','is-active','--quiet','moa-auto-trading']).returncode==0
    if active:subprocess.run(['systemctl','stop','moa-auto-trading'],check=True)
    try:
        for p,s in changes.items():p.write_text(s)
        subprocess.run(['/opt/kiwoom/.venv/bin/python','-W','ignore::ResourceWarning','-m','unittest','-q','test_trade_sources','test_auto_trading'],cwd=root,check=True)
        subprocess.run(['systemctl','restart','kiwoom-refresh'],check=True)
        if active:subprocess.run(['systemctl','start','moa-auto-trading'],check=True)
        subprocess.run(['systemctl','is-active','kiwoom-refresh'],check=True)
    except BaseException:
        for p,original in originals.items():
            if original is not None:p.write_bytes(original)
        subprocess.run(['systemctl','restart','kiwoom-refresh'],check=False)
        if active:subprocess.run(['systemctl','start','moa-auto-trading'],check=False)
        raise
    print('TRADE_TAGS_DEPLOYED', suffix, 'AUTO_PREVIOUSLY_ACTIVE',active)
    print('FILES', {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in changes})

if __name__=='__main__':deploy(json.loads(Path(sys.argv[1]).read_text()))
