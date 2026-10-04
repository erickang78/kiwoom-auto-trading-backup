"""Install supplied backup-only files. Run as root with a protected JSON bundle."""
import base64,grp,json,os,subprocess,sys
from pathlib import Path

def install(bundle):
    os.umask(0o077)
    tools=Path('/opt/kiwoom/backup-tools');tools.mkdir(mode=0o755,exist_ok=True);tools.chmod(0o755)
    status=Path('/opt/kiwoom/backup-status');status.mkdir(mode=0o750,exist_ok=True)
    os.chown(status,0,grp.getgrnam('ubuntu').gr_gid);status.chmod(0o750)
    for name in ('backup.py','recovery-public.crt'):
        dest=tools/name;dest.write_bytes(base64.b64decode(bundle[name]));dest.chmod(0o644)
    credentials=Path('/opt/kiwoom/secrets/db-backup-writer.json')
    if credentials.exists():raise RuntimeError('existing_credentials_review_required')
    credentials.write_bytes(base64.b64decode(bundle['writer-credentials.json']));credentials.chmod(0o600)
    config={'bucket':'example-backup-bucket','region':'ap-northeast-2','state_directory':'/opt/kiwoom/state','credentials':str(credentials),'certificate':str(tools/'recovery-public.crt'),'status_path':str(status/'status.json'),'temporary_directory':'/run/kiwoom-db-backup'}
    Path('/opt/kiwoom/secrets/db-backup-config.json').write_text(json.dumps(config))
    for name in ('kiwoom-db-backup.service','kiwoom-db-backup.timer'):
        dest=Path('/etc/systemd/system')/name;dest.write_bytes(base64.b64decode(bundle[name]));dest.chmod(0o644)
    subprocess.run(['systemd-analyze','verify','/etc/systemd/system/kiwoom-db-backup.service','/etc/systemd/system/kiwoom-db-backup.timer'],check=True)
    subprocess.run(['systemctl','daemon-reload'],check=True)
    subprocess.run(['systemctl','start','kiwoom-db-backup.service'],check=True)
    subprocess.run(['systemctl','enable','--now','kiwoom-db-backup.timer'],check=True)
    print('BACKUP_INSTALLED');print((status/'status.json').read_text())
if __name__=='__main__':install(json.loads(Path(sys.argv[1]).read_text()))
