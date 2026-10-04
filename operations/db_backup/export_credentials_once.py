"""One-time local handoff through the existing authenticated dashboard; no S3 upload."""
import base64,hashlib,json,os,subprocess,tempfile
from pathlib import Path
from credential_backup import snapshot_credentials

def export():
 os.umask(0o077)
 work=Path('/run/kiwoom-credential-export');work.mkdir(mode=0o700)
 page=Path('/opt/kiwoom/dashboard-source/dist/index.html');original=page.read_bytes()
 if b'credential-backup-download' in original:raise ValueError('existing_export')
 with tempfile.TemporaryDirectory(dir=work) as temporary:
  archive,count=snapshot_credentials('/opt/kiwoom/secrets',temporary)
  encrypted=work/'credentials.cms'
  subprocess.run(['openssl','cms','-encrypt','-binary','-aes-256-gcm','-outform','DER','-in',str(archive),'-out',str(encrypted),'/opt/kiwoom/backup-tools/recovery-public.crt'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 cipher=encrypted.read_bytes();sha=hashlib.sha256(cipher).hexdigest()
 link='<aside id="credential-backup-download" data-sha256="'+sha+'" data-file-count="'+str(count)+'" style="padding:20px"><a download="credentials.cms" href="data:application/octet-stream;base64,'+base64.b64encode(cipher).decode()+'">인증정보 암호화 백업 다운로드</a></aside>'
 assert original.count(b'</body>')==1
 changed=original.replace(b'</body>',link.encode()+b'</body>')
 (work/'original.html').write_bytes(original)
 (work/'handoff.json').write_text(json.dumps({'original_sha256':hashlib.sha256(original).hexdigest(),'patched_sha256':hashlib.sha256(changed).hexdigest(),'encrypted_sha256':sha,'file_count':count}))
 temp=page.with_name('index.html.credential-export-next');temp.write_bytes(changed);os.chown(temp,page.stat().st_uid,page.stat().st_gid);temp.chmod(page.stat().st_mode&0o777);temp.replace(page)
 print('CREDENTIAL_EXPORT_READY',count,sha)
if __name__=='__main__':export()
