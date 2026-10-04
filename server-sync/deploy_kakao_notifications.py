"""Add Kakao routes and observer without altering broker or trading workers."""
from pathlib import Path
import datetime,shutil,subprocess,json,os,sqlite3

def replace_once(s,old,new):
 assert s.count(old)==1,'API anchor changed: '+old
 return s.replace(old,new)
def patch_api(s):
 s=replace_once(s,'        is_price = ',"        is_kakao = self.path == '/v1/notifications/kakao'\n        is_price = is_kakao or ")
 return replace_once(s,'            if is_auto_trading:\n',"            if is_kakao:\n                from kakao_notifications import control as kakao_control\n                return self._json(200, kakao_control(body))\n            if is_auto_trading:\n")
def deploy(v):
 root=Path('/opt/kiwoom/current');api=root/'refresh_api.py';page=Path('/opt/kiwoom/dashboard-source/dist/index.html')
 def settings():
  with sqlite3.connect('file:/opt/kiwoom/state/auto-trading.sqlite3?mode=ro',uri=True) as d:return d.execute('SELECT market,strategy,enabled,revision,budget,started FROM portfolios ORDER BY market').fetchall()
 before=settings()
 original_api=api.read_text();original_html=page.read_text();assert 'kakao-notifications-module' not in original_html,'Already deployed'
 updated=patch_api(original_api);compile(updated,'refresh_api.py','exec')
 for name,text in v['files'].items():compile(text,name,'exec')
 suffix='.before-kakao-notifications-'+datetime.datetime.now().strftime('%Y%m%d%H%M%S')
 shutil.copy2(api,str(api)+suffix);shutil.copy2(page,str(page)+suffix)
 for name,text in v['files'].items():(root/name).write_text(text)
 subprocess.run(['python3','-m','unittest','test_kakao_notifications'],cwd=root,check=True)
 # Initialize privately owned state before running either process.
 subprocess.run(['sudo','-u','ubuntu','python3','-c','import kakao_notifications as k; k.control({"action":"status"})'],cwd=root,check=True)
 unit=Path('/etc/systemd/system/moa-kakao-notifications.service')
 assert not unit.exists(),'Existing notification service'
 unit.write_text('''[Unit]
Description=Personal Kakao automatic trade fill notifications
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/kiwoom/current
ExecStart=/opt/kiwoom/.venv/bin/python /opt/kiwoom/current/kakao_notifications.py
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadOnlyPaths=/opt/kiwoom/current /opt/kiwoom/secrets
ReadWritePaths=/opt/kiwoom/state
[Install]
WantedBy=multi-user.target
''')
 try:
  api.write_text(updated);page.write_text(original_html.replace('</body>','<script id="kakao-notifications-module">\n'+v['ui']+'\n</script></body>'))
  subprocess.run(['systemctl','daemon-reload'],check=True)
  subprocess.run(['systemctl','restart','kiwoom-refresh'],check=True)
  subprocess.run(['systemctl','enable','--now','moa-kakao-notifications'],check=True)
  subprocess.run(['systemctl','is-active','kiwoom-refresh','moa-auto-trading','moa-kakao-notifications'],check=True)
 except BaseException:
  api.write_text(original_api);page.write_text(original_html)
  subprocess.run(['systemctl','stop','moa-kakao-notifications'])
  subprocess.run(['systemctl','restart','kiwoom-refresh'])
  raise
 assert settings()==before,'Trading settings changed'
 print('KAKAO_NOTIFICATIONS_DEPLOYED',suffix,'APP_SETUP_PENDING')
if __name__=='__main__':deploy(json.loads(Path('/tmp/kakao-notifications-payload.json').read_text()))
