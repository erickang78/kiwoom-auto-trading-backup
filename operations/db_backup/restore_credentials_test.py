"""Decrypt and verify credentials offline; never installs or activates credentials."""
import argparse,hashlib,json,os,subprocess,tarfile,tempfile
from pathlib import Path

def restore(encrypted,key,passphrase,destination):
    destination=Path(destination).resolve()
    if destination.exists() or str(destination).startswith('/opt/kiwoom'):raise ValueError('unsafe_restore_destination')
    destination.mkdir(parents=True,mode=0o700)
    try:
        with tempfile.TemporaryDirectory(prefix='credential-rehearsal-') as temporary:
            archive=Path(temporary)/'credentials.tar.gz'
            subprocess.run(['openssl','cms','-decrypt','-binary','-inform','DER','-in',str(encrypted),'-inkey',str(key),'-passin','file:'+str(passphrase),'-out',str(archive)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            with tarfile.open(archive) as tar:
                members=tar.getmembers();names=[m.name for m in members]
                if len(names)!=len(set(names)) or 'manifest.json' not in names:raise ValueError('invalid_archive')
                for m in members:
                    parts=Path(m.name).parts
                    if not m.isfile() or m.size>1024*1024 or (m.name!='manifest.json' and not (len(parts)==2 and parts[0]=='secrets' and parts[1] not in ('.','..'))):raise ValueError('unsafe_archive_member')
                manifest=json.loads(tar.extractfile('manifest.json').read())
                if manifest.get('format')!=1 or manifest.get('kind')!='credentials' or not manifest.get('files'):raise ValueError('invalid_manifest')
                expected={'secrets/'+x['name'] for x in manifest['files']}
                if expected!=set(names)-{'manifest.json'} or len(expected)!=len(manifest['files']):raise ValueError('invalid_manifest_members')
                (destination/'secrets').mkdir(mode=0o700)
                for entry in manifest['files']:
                    name='secrets/'+entry['name'];data=tar.extractfile(name).read()
                    if len(data)!=entry['bytes'] or hashlib.sha256(data).hexdigest()!=entry['sha256']:raise ValueError('credential_checksum_mismatch')
                    fd=os.open(destination/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                    with os.fdopen(fd,'wb') as f:f.write(data)
        result={'verified':True,'file_count':len(expected),'checksums_match':True,'installed':False,'services_started':False}
        (destination/'restore-verification.json').write_text(json.dumps(result,indent=2));return result
    except Exception:
        (destination/'RESTORE_FAILED').touch(mode=0o600);raise
if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('archive','key','passphrase','destination'):p.add_argument('--'+name,required=True)
    a=p.parse_args();print(json.dumps(restore(a.archive,a.key,a.passphrase,a.destination)))
