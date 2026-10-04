"""Install daily code and DB schedules from an operator-provided protected bundle."""
import base64,datetime,json,os,shutil,subprocess
from pathlib import Path

def install(bundle):
 os.umask(0o077)
 root=Path('/opt/kiwoom');tools=root/'backup-tools';archive=root/'backups'/('daily-schedule-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ'));archive.mkdir(mode=0o700)
 subprocess.run(['systemctl','stop','kiwoom-db-backup.timer'],check=True)
 active=subprocess.check_output(['systemctl','show','kiwoom-db-backup.service','-p','ActiveState','--value'],text=True).strip()
 if active in ('activating','active','deactivating'):raise RuntimeError('wait_for_running_db_backup')
 locations={
  'backup.py':tools/'backup.py','backup_status.py':root/'backup_status.py','dashboard-status.js':tools/'dashboard-status.js',
  'backup_code.py':tools/'backup_code.py','check_repository_secrets.py':tools/'check_repository_secrets.py',
  'kiwoom-db-backup.timer':Path('/etc/systemd/system/kiwoom-db-backup.timer'),
  'kiwoom-code-backup.timer':Path('/etc/systemd/system/kiwoom-code-backup.timer'),
  'kiwoom-code-backup.service':Path('/etc/systemd/system/kiwoom-code-backup.service')}
 for name,target in locations.items():
  if target.exists():shutil.copy2(target,archive/name)
  target.write_bytes(base64.b64decode(bundle[name]));target.chmod(0o644)
 code=root/'code-backup';code.mkdir(mode=0o700,exist_ok=True)
 for name,target in [('github-deploy-key',root/'secrets/github-backup-key'),('github_known_hosts',code/'github_known_hosts')]:
  if target.exists():raise RuntimeError('existing_code_credential_review_required')
  target.write_bytes(base64.b64decode(bundle[name]));target.chmod(0o600)
 subprocess.run(['systemd-analyze','verify',str(locations['kiwoom-code-backup.service']),str(locations['kiwoom-code-backup.timer']),str(locations['kiwoom-db-backup.timer'])],check=True)
 subprocess.run(['systemctl','daemon-reload'],check=True)
 subprocess.run(['systemctl','restart','moa-dashboard'],check=True)
 subprocess.run(['systemctl','enable','--now','kiwoom-db-backup.timer','kiwoom-code-backup.timer'],check=True)
 subprocess.run(['systemctl','start','--no-block','kiwoom-code-backup.service'],check=True)
 print('DAILY_SCHEDULE_INSTALLED',str(archive))
