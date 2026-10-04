"""Deploy opt-in engine and UI, preserving all existing state and modules."""
import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def replace_once(source,old,new):
    assert source.count(old)==1, 'Unexpected anchor: '+old[:70]
    return source.replace(old,new)


def patch_api(source):
    source=replace_once(source,'        is_trading_control = ',"        is_auto_trading = self.path == '/v1/trading/auto'\n        is_trading_control = ")
    source=replace_once(source,'        is_price = is_trading_control or ', '        is_price = is_auto_trading or is_trading_control or ')
    return replace_once(source,'            if is_trading_control:\n',"            if is_auto_trading:\n                from auto_trading import control as auto_control\n                return self._json(200, auto_control(body))\n            if is_trading_control:\n")


def patch_html(source,ui):
    assert 'id="auto-trading-execution-module"' not in source
    return replace_once(source,'</body>','<script id="auto-trading-execution-module">\n'+ui+'\n</script></body>')


def deploy(payload):
    root=Path('/opt/kiwoom/current');api=root/'refresh_api.py';html=Path('/opt/kiwoom/dashboard-source/dist/index.html');unit=Path('/etc/systemd/system/moa-auto-trading.service')
    assert not (root/'auto_trading.py').exists(), 'Existing engine requires explicit update deployment'
    changes=[(api,patch_api(api.read_text())),(html,patch_html(html.read_text(),payload['ui']))]
    changes += [(root/name,content) for name,content in payload['files'].items()]
    service='''[Unit]
Description=Opt-in real KR/US strategy trading (disabled until user starts)
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/kiwoom/current
ExecStart=/opt/kiwoom/.venv/bin/python /opt/kiwoom/current/auto_trading.py
Restart=on-failure
RestartSec=10
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadOnlyPaths=/opt/kiwoom/current /opt/kiwoom/secrets
ReadWritePaths=/opt/kiwoom/state
[Install]
WantedBy=multi-user.target
'''
    changes.append((unit,service))
    for path,content in changes:
        if path.suffix=='.py':compile(content,str(path),'exec')
    suffix='.before-auto-trading-'+datetime.datetime.now().strftime('%Y%m%d%H%M%S')
    originals={path:path.read_bytes() if path.exists() else None for path,_ in changes}
    for path,_ in changes:
        if path.exists():shutil.copy2(path,path.with_name(path.name+suffix))
    try:
        for path,content in changes:
            tmp=path.with_name(path.name+'.auto-new');tmp.write_text(content);tmp.chmod(0o644);tmp.replace(path)
        subprocess.run(['/opt/kiwoom/.venv/bin/python','-m','unittest','-q','test_auto_trading','test_signal_validation','test_signal_period','test_trading_control'],cwd=root,check=True)
        # Initialize only new DB as service user; no order/account network calls.
        subprocess.run(['sudo','-u','ubuntu','/opt/kiwoom/.venv/bin/python','-c',"from auto_trading import control; print('AUTO_DEFAULT_DISABLED', not control({'market':'KR'})['enabled'], not control({'market':'US'})['enabled'])"],cwd=root,check=True)
        os.chmod('/opt/kiwoom/state/auto-trading.sqlite3', 0o600)
        subprocess.run(['systemctl','daemon-reload'],check=True)
        subprocess.run(['systemctl','restart','kiwoom-refresh'],check=True)
        subprocess.run(['systemctl','enable','--now','moa-auto-trading'],check=True)
        subprocess.run(['systemctl','is-active','kiwoom-refresh','moa-auto-trading','moa-signal-validation'],check=True)
    except BaseException:
        subprocess.run(['systemctl','stop','moa-auto-trading'],check=False)
        for path,content in originals.items():
            if content is not None:path.write_bytes(content)
            elif path.exists():path.unlink()
        subprocess.run(['systemctl','daemon-reload'],check=False)
        subprocess.run(['systemctl','restart','kiwoom-refresh'],check=False)
        raise
    print('AUTO_TRADING_DEPLOYED',suffix)

if __name__=='__main__':deploy(json.loads(Path(sys.argv[1]).read_text()))
