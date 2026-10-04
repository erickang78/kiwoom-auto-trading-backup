import getpass, json, os, pwd
from pathlib import Path
target=Path('/opt/kiwoom/secrets/upbit-credentials.json')
access_key=getpass.getpass('Upbit Access Key (hidden): ').strip(); secret_key=getpass.getpass('Upbit Secret Key (hidden): ').strip()
if not access_key or not secret_key: raise SystemExit('Both keys are required; nothing was saved.')
temp=target.with_suffix('.tmp'); temp.write_text(json.dumps({'access_key':access_key,'secret_key':secret_key})); os.chmod(temp,0o600); u=pwd.getpwnam("ubuntu"); os.chown(temp,u.pw_uid,u.pw_gid); temp.replace(target); print('UPBIT_KEYS_SAVED')
