import getpass
import json
import os
import pwd
from pathlib import Path

target = Path('/opt/kiwoom/secrets/upbit-credentials.json')
access_key = getpass.getpass('Upbit Access Key (hidden): ').strip()
secret_key = getpass.getpass('Upbit Secret Key (hidden): ').strip()
if not access_key or not secret_key:
    raise SystemExit('Both keys are required; nothing was saved.')
target.parent.mkdir(parents=True, exist_ok=True)
temp = target.with_suffix('.tmp')
temp.write_text(json.dumps({'access_key': access_key, 'secret_key': secret_key}))
os.chmod(temp, 0o600)
service_user = pwd.getpwnam('ubuntu')
os.chown(temp, service_user.pw_uid, service_user.pw_gid)
temp.replace(target)
print('UPBIT_KEYS_SAVED')
