"""AWS deployment: sudo python3 deploy_signal_validation.py /tmp/signal-payload.json."""
import datetime as dt
import json
import os
from pathlib import Path
import pwd
import subprocess
import sys
import tempfile

payload = json.loads(Path(sys.argv[1]).read_text())
root = Path('/opt/kiwoom/current')
api = root / 'refresh_api.py'
html = Path('/opt/kiwoom/dashboard-source/dist/index.html')
a, h = api.read_text(), html.read_text()
if 'from signal_validation import status as signal_status' not in a:
    needle = '        is_price = is_strategy or '
    assert a.count(needle) == 1
    a = 'from signal_validation import status as signal_status\n' + a
    a = a.replace(needle, "        is_signal_validation = self.path == '/v1/market/signal-validation'\n        is_price = is_signal_validation or is_strategy or ", 1)
    needle = '            if is_strategy:\n'
    assert a.count(needle) == 1
    a = a.replace(needle, "            if is_signal_validation:\n                return self._json(200, signal_status(str(body.get('action', 'status'))))\n" + needle, 1)
old_call = "signal_status(str(body.get('action', 'status')))"
new_call = "signal_status(str(body.get('action', 'status')), market=str(body.get('market', 'US')), strategy=str(body.get('strategy', 'trend')))"
if old_call in a:
    assert a.count(old_call) == 1
    a = a.replace(old_call, new_call)
assert new_call in a
marker = '<script id="signal-validation-module">'
if marker in h:
    start = h.index(marker); end = h.index('</script>', start) + len('</script>')
    h = h[:start] + marker + '\n' + payload['ui'] + '\n</script>' + h[end:]
else:
    assert h.count('</body>') == 1
    h = h.replace('</body>', marker + '\n' + payload['ui'] + '\n</script></body>', 1)
unit = '''[Unit]
Description=KR/US five-strategy paper trading (no orders)
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/kiwoom/current
ExecStart=/opt/kiwoom/.venv/bin/python /opt/kiwoom/current/signal_validation.py
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
changes = [(root/'signal_validation.py', payload['engine']),
           (root/'test_signal_validation.py', payload['tests']), (api, a), (html, h),
           (Path('/etc/systemd/system/moa-signal-validation.service'), unit)]
for path, content in changes:
    if path.suffix == '.py': compile(content, str(path), 'exec')
with tempfile.TemporaryDirectory() as tmp:
    Path(tmp, 'signal_validation.py').write_text(payload['engine'])
    Path(tmp, 'test_signal_validation.py').write_text(payload['tests'])
    subprocess.run(['/opt/kiwoom/.venv/bin/python', '-m', 'unittest', '-v', 'test_signal_validation'], cwd=tmp, check=True)
uid = pwd.getpwnam('ubuntu').pw_uid
suffix = '.before-signal-validation-' + dt.datetime.now().strftime('%Y%m%d%H%M%S')
# Stop the worker before replacing code and back up the existing database.
subprocess.run(['systemctl', 'stop', 'moa-signal-validation'], check=True)
import sqlite3
database = Path('/opt/kiwoom/state/signal-validation.sqlite3')
if database.exists():
    with sqlite3.connect(database) as source, sqlite3.connect(str(database) + suffix) as backup:
        source.backup(backup)
    os.chmod(str(database) + suffix, 0o600)
for path, content in changes:
    if path.exists():
        path.with_name(path.name + suffix).write_text(path.read_text())
    tmp = path.with_name(path.name + '.signal-new')
    tmp.write_text(content)
    os.chmod(tmp, 0o644)
    tmp.replace(path)
state_dir = Path('/opt/kiwoom/state')
assert state_dir.is_dir()
subprocess.run(['systemctl', 'daemon-reload'], check=True)
subprocess.run(['systemctl', 'restart', 'kiwoom-refresh'], check=True)
subprocess.run(['systemctl', 'enable', '--now', 'moa-signal-validation'], check=True)
subprocess.run(['systemctl', 'restart', 'moa-signal-validation'], check=True)
subprocess.run(['systemctl', 'is-active', 'kiwoom-refresh', 'moa-signal-validation'], check=True)
print('SIGNAL_VALIDATION_DEPLOYED', suffix)
