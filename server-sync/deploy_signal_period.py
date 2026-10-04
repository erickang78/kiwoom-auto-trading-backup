"""Deploy period returns while preserving every existing trading record."""
import datetime as dt
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys

payload=json.loads(Path(sys.argv[1]).read_text())
root=Path('/opt/kiwoom/current')
api=root/'refresh_api.py'
a=api.read_text()
old="signal_status(str(body.get('action', 'status')), market=str(body.get('market', 'US')), strategy=str(body.get('strategy', 'trend')))"
new="signal_status(str(body.get('action', 'status')), market=str(body.get('market', 'US')), strategy=str(body.get('strategy', 'trend')), days=body.get('days', 5))"
assert a.count(old)==1
a=a.replace(old,new)
html=Path('/opt/kiwoom/dashboard-source/dist/index.html');h=html.read_text()
for name,key in [('signal-validation','ui'),('trading-control','control_ui')]:
    marker='<script id="'+name+'-module">'
    assert h.count(marker)==1
    start=h.index(marker)+len(marker);end=h.index('</script>',start)
    h=h[:start]+'\n'+payload[key]+'\n'+h[end:]
changes=[(api,a),(html,h),(root/'signal_validation.py',payload['engine']),
         (root/'test_signal_period.py',payload['period_tests'])]
for p,s in changes:
    if p.suffix=='.py':compile(s,str(p),'exec')
suffix='.before-signal-period-'+dt.datetime.now().strftime('%Y%m%d%H%M%S')
subprocess.run(['systemctl','stop','moa-signal-validation'],check=True)
try:
    database=Path('/opt/kiwoom/state/signal-validation.sqlite3')
    with sqlite3.connect(database) as source,sqlite3.connect(str(database)+suffix) as backup:
        source.backup(backup)
        original_events=source.execute('SELECT * FROM events ORDER BY id').fetchall()
        original_states=source.execute('SELECT * FROM state ORDER BY id').fetchall()
    Path(str(database)+suffix).chmod(0o600)
    for p,s in changes:
        shutil.copy2(p,p.with_name(p.name+suffix)) if p.exists() else None
        tmp=p.with_name(p.name+'.period-new');tmp.write_text(s);tmp.chmod(0o644);tmp.replace(p)
    subprocess.run(['/opt/kiwoom/.venv/bin/python','-m','unittest','test_signal_validation','test_signal_period','test_trading_control'],cwd=root,check=True)
    with sqlite3.connect(database) as source:
        assert original_events==source.execute('SELECT * FROM events ORDER BY id').fetchall()
        assert original_states==source.execute('SELECT * FROM state ORDER BY id').fetchall()
    subprocess.run(['systemctl','restart','kiwoom-refresh'],check=True)
except BaseException:
    for p,s in changes:
        backup=p.with_name(p.name+suffix)
        if backup.exists():shutil.copy2(backup,p)
    subprocess.run(['systemctl','restart','kiwoom-refresh'],check=True)
    raise
finally:
    subprocess.run(['systemctl','start','moa-signal-validation'],check=True)
subprocess.run(['systemctl','is-active','kiwoom-refresh','moa-signal-validation'],check=True)
print('SIGNAL_PERIOD_DEPLOYED_RECORDS_PRESERVED',suffix)
