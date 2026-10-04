"""Offline restore rehearsal only: never starts services or imports trading code."""
import argparse, hashlib, json, os, sqlite3, subprocess, tarfile, tempfile
from pathlib import Path
from backup import DATABASES,inspect_db,digest

def restore(encrypted,key,passphrase,destination):
    destination=Path(destination).resolve()
    if destination.exists():raise ValueError('destination_must_not_exist')
    if str(destination).startswith('/opt/kiwoom'):raise ValueError('production_restore_forbidden')
    destination.mkdir(parents=True,mode=0o700)
    try:
        with tempfile.TemporaryDirectory(prefix='kiwoom-decrypt-') as temp:
            archive=Path(temp)/'restored.tar.gz'
            subprocess.run(['openssl','cms','-decrypt','-binary','-inform','DER','-in',str(encrypted),'-inkey',str(key),'-passin','file:'+str(passphrase),'-out',str(archive)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            with tarfile.open(archive) as tar:
                members=tar.getmembers();allowed=set(DATABASES)|{'manifest.json'}
                if len(members)!=len(allowed) or {m.name for m in members}!=allowed or not all(m.isfile() for m in members):raise ValueError('invalid_archive_members')
                for m in members:
                    if m.size>100*1024*1024:raise ValueError('archive_too_large')
                    p=destination/m.name;p.write_bytes(tar.extractfile(m).read());p.chmod(0o600)
        manifest=json.loads((destination/'manifest.json').read_text())
        if manifest.get('format')!=1 or {d['name'] for d in manifest['databases']}!=set(DATABASES):raise ValueError('invalid_manifest')
        for entry in manifest['databases']:
            path=destination/entry['name']
            if digest(path)!=entry['sha256'] or path.stat().st_size!=entry['bytes'] or inspect_db(path)!=entry['tables']:raise ValueError('restored_data_mismatch')
        # Extra operational fence on the rehearsal copies; original backup is untouched.
        with sqlite3.connect(destination/'trading-control.sqlite3') as db:db.execute('UPDATE control SET enabled=0')
        with sqlite3.connect(destination/'auto-trading.sqlite3') as db:db.execute('UPDATE portfolios SET enabled=0')
        with sqlite3.connect(destination/'signal-validation.sqlite3') as db:db.execute('UPDATE state SET enabled=0')
        with sqlite3.connect(destination/'kakao-notifications.sqlite3') as db:
            for rowid,raw in db.execute('SELECT id,data FROM settings').fetchall():
                data=json.loads(raw);data['connected']=False;db.execute('UPDATE settings SET data=? WHERE id=?',(json.dumps(data),rowid))
        report={'verified':True,'database_count':len(DATABASES),'source_checksums_match':True,'row_counts_match':True,'integrity_check':'ok','rehearsal_trading_disabled':True,'rehearsal_notifications_disabled':True,'services_started':False}
        (destination/'restore-verification.json').write_text(json.dumps(report,indent=2))
        return report
    except Exception:
        # Leave a clearly marked private failed rehearsal for diagnosis, never activate it.
        (destination/'RESTORE_FAILED').touch(mode=0o600)
        raise
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--archive',required=True);p.add_argument('--key',required=True);p.add_argument('--passphrase',required=True);p.add_argument('--destination',required=True);a=p.parse_args()
    print(json.dumps(restore(a.archive,a.key,a.passphrase,a.destination)))
