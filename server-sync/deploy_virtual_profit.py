"""Anchored deployment; preserves unrelated server changes and trading state."""
import datetime, py_compile, subprocess, tempfile
from pathlib import Path
ROOT=Path('/opt/kiwoom/current')
PAGE=Path('/opt/kiwoom/dashboard-source/dist/index.html')
def deploy(payload):
    old=(ROOT/'auto_trading.py').read_text()
    anchor="        from real_profit_report import read_report\n        return read_report(path, market, report_strategy)"
    assert old.count(anchor)==1 and 'report_source' not in old
    new=old.replace(anchor,payload['branch'])
    page=PAGE.read_text();marker='<script id="profit-report-module">'
    assert page.count(marker)==1
    start=page.index(marker)+len(marker);end=page.index('</script>',start)
    html=page[:start]+'\n'+payload['ui']+'\n'+page[end:]
    names=['real_profit_report.py','virtual_profit_report.py','test_real_profit_report.py','test_virtual_profit_report.py']
    with tempfile.TemporaryDirectory() as directory:
        tmp=Path(directory)
        for name in names:(tmp/name).write_text(payload[name])
        (tmp/'signal_validation.py').write_text((ROOT/'signal_validation.py').read_text())
        (tmp/'auto_trading.py').write_text(new)
        for f in tmp.glob('*.py'):py_compile.compile(str(f),doraise=True)
        subprocess.run(['python3','-m','unittest','test_real_profit_report','test_virtual_profit_report'],cwd=tmp,check=True)
    files={ROOT/name:payload[name] for name in names}
    files.update({ROOT/'auto_trading.py':new,PAGE:html})
    backups={f:f.read_bytes() if f.exists() else None for f in files}
    suffix='.before-virtual-profit-'+datetime.datetime.now().strftime('%Y%m%d%H%M%S')
    for f,b in backups.items():
        if b is not None:f.with_name(f.name+suffix).write_bytes(b)
    try:
        for f,text in files.items():
            tmp=f.with_name(f.name+'.next');tmp.write_text(text);tmp.replace(f)
        subprocess.run(['systemctl','restart','kiwoom-refresh'],check=True)
        subprocess.run(['systemctl','is-active','kiwoom-refresh','moa-auto-trading'],check=True)
    except Exception:
        for f,b in backups.items():
            if b is not None:f.write_bytes(b)
        subprocess.run(['systemctl','restart','kiwoom-refresh']);raise
    print('VIRTUAL_PROFIT_DEPLOYED',suffix)
