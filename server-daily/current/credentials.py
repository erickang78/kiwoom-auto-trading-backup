"""Local server credential storage with restrictive filesystem permissions."""
import getpass
import json
import os
import stat
from pathlib import Path


SECRET_DIR = Path('/opt/kiwoom/secrets')
DEFAULT_PATH = SECRET_DIR / 'mock-credentials.json'
REAL_PATH = SECRET_DIR / 'real-credentials.json'
GOLD_PATH = SECRET_DIR / 'gold-credentials.json'


def load_credentials(path=DEFAULT_PATH):
    if path.exists():
        if stat.S_IMODE(path.stat().st_mode) & 0o077:
            raise PermissionError('Credential file permissions must be 600')
        data = json.loads(path.read_text())
        key, secret = data.get('app_key'), data.get('app_secret')
        if isinstance(key, str) and key and isinstance(secret, str) and secret:
            return key, secret
        raise ValueError('Stored credentials are incomplete')
    return (
        getpass.getpass('MOCK App Key (hidden): '),
        getpass.getpass('MOCK App Secret (hidden): '),
    )


def save_interactive(path=DEFAULT_PATH):
    label = 'GOLD' if path == GOLD_PATH else ('REAL' if path == REAL_PATH else 'MOCK')
    key = getpass.getpass(f'{label} App Key to save (hidden): ')
    secret = getpass.getpass(f'{label} App Secret to save (hidden): ')
    if not key or not secret:
        raise ValueError('Credentials cannot be empty')
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    temporary = path.with_suffix('.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as file:
        json.dump({'app_key': key, 'app_secret': secret}, file)
        file.flush()
        os.fsync(file.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)
    print('CREDENTIALS_SAVED: mode 600; values were not printed')


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Store Kiwoom credentials with mode 600')
    parser.add_argument('--environment', choices=('mock', 'real', 'gold'), default='mock')
    args = parser.parse_args()
    paths = {'mock': DEFAULT_PATH, 'real': REAL_PATH, 'gold': GOLD_PATH}
    save_interactive(paths[args.environment])
