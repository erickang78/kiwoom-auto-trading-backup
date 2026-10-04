"""Patch cumulative defaults and short windows without changing validation records."""
from pathlib import Path
import datetime as dt
import shutil
import subprocess
import sys


def deploy(root, html, transform):
    engine=root/'signal_validation.py'
    api=root/'refresh_api.py'
    original={p:p.read_text() for p in (engine,api,html)}
    updated=transform(original,engine,api,html)
    for p,s in updated.items():
        if p.suffix=='.py':compile(s,str(p),'exec')
    suffix='.before-signal-cumulative-'+dt.datetime.now().strftime('%Y%m%d%H%M%S')
    for p in original:shutil.copy2(p,str(p)+suffix)
    try:
        for p,s in updated.items():
            tmp=p.with_name(p.name+'.cumulative-new');tmp.write_text(s);tmp.chmod(p.stat().st_mode & 0o777);tmp.replace(p)
        subprocess.run(['/opt/kiwoom/.venv/bin/python','-m','unittest','test_signal_validation','test_signal_period','test_trading_control'],cwd=root,check=True)
        subprocess.run(['systemctl','restart','kiwoom-refresh'],check=True)
        subprocess.run(['systemctl','is-active','kiwoom-refresh','moa-signal-validation'],check=True)
    except BaseException:
        for p,s in original.items():p.write_text(s)
        subprocess.run(['systemctl','restart','kiwoom-refresh'],check=True)
        raise
    print('CUMULATIVE_DEPLOYED',suffix)


if __name__ == '__main__':
    import json
    payload=json.loads(Path(sys.argv[1]).read_text())
    def transform(original,engine,api,html):
        a=original[api]
        old="days=body.get('days', 5)"
        assert a.count(old)==1
        a=a.replace(old,"days=body.get('days')")
        h=original[html]
        tag='<script id="signal-validation-module">'
        assert h.count(tag)==1
        start=h.index(tag)+len(tag)
        end=h.index('</script>',start)
        h=h[:start]+'\n'+payload['ui']+'\n'+h[end:]
        return {api:a,engine:payload['engine'],html:h}
    deploy(Path('/opt/kiwoom/current'),Path('/opt/kiwoom/dashboard-source/dist/index.html'),transform)
