"""Capture active source/configuration without changing trading services.
Invoked by the operator with an archive passphrase on stdin. No credential files or databases are exported.
"""
from pathlib import Path
import base64, datetime, hashlib, io, json, os, subprocess, sys, tarfile
os.umask(0o077)
password=sys.stdin.read().strip()
assert len(password)>=40
root=Path('/opt/kiwoom');current=root/'current';page=root/'dashboard-source/dist/index.html'
stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
backup=root/'backups'/('source-'+stamp);backup.mkdir(parents=True,mode=0o700)
files={}
for p in current.iterdir():
    if p.is_file() and p.suffix in ('.py','.sh','.toml','.txt','.ini','.cfg'):
        files['current/'+p.name]=p
for p in root.glob('*.py'):files['root/'+p.name]=p
for p in (root/'dashboard-source/dist').rglob('*'):
    if p.is_file() and p.suffix in ('.html','.js','.css','.svg','.png','.ico') and '.git' not in p.parts:
        files['dashboard/dist/'+str(p.relative_to(root/'dashboard-source/dist'))]=p
for pattern in ('moa-*.service','kiwoom-*.service','moa-*.timer','kiwoom-*.timer'):
    for p in Path('/etc/systemd/system').glob(pattern):files['config/systemd/'+p.name]=p
for p in Path('/etc/systemd/system').glob('kiwoom-*.service.d/*.conf'):files['config/systemd/'+str(p.relative_to('/etc/systemd/system'))]=p
files['config/Caddyfile']=Path('/etc/caddy/Caddyfile')
manifest={'captured_at':stamp,'current_target':str(current.resolve()),'files':[],'excluded':['credential files','databases','old .before/.bak files','logs','account snapshots']}
raw=backup/'source-original.tar.gz'
with tarfile.open(raw,'w:gz') as tar:
    for name,p in sorted(files.items()):
        data=p.read_bytes();info=tarfile.TarInfo(name);info.size=len(data);info.mode=p.stat().st_mode & 0o777;tar.addfile(info,io.BytesIO(data))
        manifest['files'].append({'path':name,'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),'mode':oct(info.mode)})
    for user in ('ubuntu','root'):
        result=subprocess.run(['crontab','-u',user,'-l'],capture_output=True)
        if result.returncode==0:
            data=result.stdout;info=tarfile.TarInfo('config/crontab-'+user);info.size=len(data);info.mode=0o600;tar.addfile(info,io.BytesIO(data))
    result=subprocess.run([str(root/'.venv/bin/python'),'-m','pip','freeze'],capture_output=True,check=True)
    data=result.stdout;info=tarfile.TarInfo('requirements-server.txt');info.size=len(data);tar.addfile(info,io.BytesIO(data))
    data=json.dumps(manifest,indent=2).encode();info=tarfile.TarInfo('manifest.json');info.size=len(data);tar.addfile(info,io.BytesIO(data))
(backup/'manifest.json').write_text(json.dumps(manifest,indent=2))
encrypted=backup/'source-original.tar.gz.enc'
subprocess.run(['openssl','enc','-aes-256-cbc','-salt','-pbkdf2','-iter','200000','-in',str(raw),'-out',str(encrypted),'-pass','stdin'],input=password.encode(),check=True)
original=page.read_bytes();assert b'id="source-backup-download"' not in original
(backup/'page-before-download.html').write_bytes(original)
encoded=base64.b64encode(encrypted.read_bytes()).decode()
link='<aside id="source-backup-download" style="padding:16px;text-align:center"><a download="source-original.tar.gz.enc" href="data:application/octet-stream;base64,'+encoded+'">운영 원본 암호화 백업 다운로드</a></aside>'
patched=original.decode().replace('</body>',link+'</body>');temp=page.with_name(page.name+'.capture-next');temp.write_text(patched);os.chmod(temp,page.stat().st_mode & 0o777);os.chown(temp,page.stat().st_uid,page.stat().st_gid);temp.replace(page)
(root/'backups/latest-source-capture').write_text(str(backup))
print('SOURCE_CAPTURE_OK',len(files),'files',len(encrypted.read_bytes()),'encrypted bytes')
print('ENCRYPTED_SHA256',hashlib.sha256(encrypted.read_bytes()).hexdigest())
print('BACKUP_DIRECTORY',backup)
