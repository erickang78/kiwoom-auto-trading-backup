"""Patch a stopped real-trading engine; never restart a trading portfolio or send orders."""
import base64
import datetime as dt
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile

ROOT=Path('/opt/kiwoom/current')
STATE=Path('/opt/kiwoom/state/auto-trading.sqlite3')

def snapshot():
    with sqlite3.connect('file:'+str(STATE)+'?mode=ro',uri=True) as db:
        portfolios=db.execute('SELECT * FROM portfolios ORDER BY market').fetchall()
        assert all(not row[2] for row in portfolios), 'Trading must remain stopped during this deployment'
        intents=db.execute('SELECT * FROM intents ORDER BY id').fetchall()
    return portfolios,intents

def deploy(payload):
    engine=ROOT/'auto_trading.py';original=engine.read_text();candidate=original
    for old,new in payload['ops']:
        assert candidate.count(old)==1, 'Unexpected server code anchor: '+old[:80]
        candidate=candidate.replace(old,new,1)
    compile(candidate,str(engine),'exec')
    before=snapshot()
    suffix='.before-order-repair-'+dt.datetime.now().strftime('%Y%m%d%H%M%S')
    files={'auto_trading.py':candidate,**payload['tests']}
    for name,source in files.items():compile(source,name,'exec')
    with tempfile.TemporaryDirectory(prefix='order-repair-',dir='/tmp') as directory:
        stage=Path(directory);stage.chmod(0o755)
        for name,source in files.items():
            (stage/name).write_text(source);(stage/name).chmod(0o644)
        env=dict(os.environ,PYTHONPATH=str(ROOT),PYTHONDONTWRITEBYTECODE='1')
        subprocess.run(['sudo','-u','ubuntu','env','PYTHONPATH='+str(ROOT),'PYTHONDONTWRITEBYTECODE=1','/opt/kiwoom/.venv/bin/python','-m','unittest','-q','test_auto_trading','test_quantity_rule','test_auto_performance','test_auto_performance_history'],cwd=stage,env=env,check=True)
    assert snapshot()==before, 'Trading state changed during validation'
    assert engine.read_text()==original, 'Engine changed during validation'
    originals={name:(ROOT/name).read_bytes() if (ROOT/name).exists() else None for name in files}
    for name,content in originals.items():
        if content is not None:shutil.copy2(ROOT/name,ROOT/(name+suffix))
    backup=STATE.with_name(STATE.name+suffix)
    source=sqlite3.connect('file:'+str(STATE)+'?mode=ro',uri=True);target=sqlite3.connect(backup)
    source.backup(target);source.close();target.close();backup.chmod(0o600)
    try:
        for name,source in files.items():
            tmp=ROOT/(name+'.order-repair-new');tmp.write_text(source);tmp.chmod(0o644);tmp.replace(ROOT/name)
        subprocess.run(['systemctl','restart','moa-auto-trading','kiwoom-refresh'],check=True)
        subprocess.run(['systemctl','is-active','moa-auto-trading','kiwoom-refresh','moa-signal-validation','moa-kakao-notifications'],check=True)
        assert snapshot()==before, 'Trading state changed after deployment'
    except BaseException:
        for name,content in originals.items():
            if content is not None:(ROOT/name).write_bytes(content)
            elif (ROOT/name).exists():(ROOT/name).unlink()
        subprocess.run(['systemctl','restart','moa-auto-trading','kiwoom-refresh'],check=False)
        raise
    print('ORDER_RELIABILITY_DEPLOYED', hashlib.sha256(candidate.encode()).hexdigest(), flush=True)
    print('PORTFOLIOS_DISABLED_AND_ALL_ORDER_RECORDS_PRESERVED',len(before[1]),flush=True)
    print('BACKUP',backup,flush=True)

if __name__=='__main__':
    import sys
    deploy(json.loads(Path(sys.argv[1]).read_text()))
