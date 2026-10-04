"""Read-only SQLite snapshots, authenticated encryption, write-only S3 upload.
No imports of trading workers or broker clients. Each database is individually
consistent; cross-database recovery must reconcile broker records before trading.
"""
import argparse, base64, datetime as dt, hashlib, hmac, io, json, os, sqlite3, subprocess, tarfile, tempfile, time, uuid
from pathlib import Path
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo
DATABASES=('auto-trading.sqlite3','signal-validation.sqlite3','manual-orders.sqlite3','trading-control.sqlite3','kakao-notifications.sqlite3')

def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def quote_identifier(value): return '"'+value.replace('"','""')+'"'
def inspect_db(path):
    db=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True,timeout=10)
    try:
        if db.execute('PRAGMA integrity_check').fetchall()!=[('ok',)]:raise ValueError('database_integrity')
        if db.execute('PRAGMA foreign_key_check').fetchall():raise ValueError('database_foreign_keys')
        names=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {n:db.execute('SELECT COUNT(*) FROM '+quote_identifier(n)).fetchone()[0] for n in names}
    finally:db.close()

def snapshot(state,directory,now=None):
    now=now or dt.datetime.now(dt.timezone.utc)
    manifest={'format':1,'started_at':now.isoformat(),'consistency':'per-database; reconcile broker before resuming','databases':[]}
    for name in DATABASES:
        source=Path(state)/name
        if not source.is_file():raise FileNotFoundError('required_database_missing: '+name)
        target=Path(directory)/name
        start=time.monotonic()
        def progress(status,remaining,total):
            if time.monotonic()-start>60:raise TimeoutError('snapshot_timeout')
        src=sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True,timeout=10)
        dst=sqlite3.connect(target)
        try:src.backup(dst,pages=128,progress=progress,sleep=.1)
        finally:dst.close();src.close()
        target.chmod(0o600)
        manifest['databases'].append({'name':name,'sha256':digest(target),'bytes':target.stat().st_size,'tables':inspect_db(target),'completed_at':dt.datetime.now(dt.timezone.utc).isoformat()})
    manifest['completed_at']=dt.datetime.now(dt.timezone.utc).isoformat()
    (Path(directory)/'manifest.json').write_text(json.dumps(manifest,sort_keys=True))
    archive=Path(directory)/'databases.tar.gz'
    with tarfile.open(archive,'w:gz') as tar:
        for name in (*DATABASES,'manifest.json'):tar.add(Path(directory)/name,arcname=name,recursive=False)
    return archive,manifest

def encrypt(archive,certificate,output):
    subprocess.run(['openssl','cms','-encrypt','-binary','-aes-256-gcm','-outform','DER','-in',str(archive),'-out',str(output),str(certificate)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    Path(output).chmod(0o600)

def signed_request(service,region,host,method,path,body,credentials,extra=None,now=None):
    now=now or dt.datetime.now(dt.timezone.utc);stamp=now.strftime('%Y%m%dT%H%M%SZ');day=stamp[:8]
    content_hash=hashlib.sha256(body).hexdigest()
    headers={'host':host,'x-amz-date':stamp,'x-amz-content-sha256':content_hash,**(extra or {})}
    if credentials.get('session_token'):headers['x-amz-security-token']=credentials['session_token']
    keys=sorted(headers);canonical_headers=''.join(k+':'+headers[k].strip()+'\n' for k in keys)
    canonical='\n'.join((method,path,'',canonical_headers,';'.join(keys),content_hash))
    scope='/'.join((day,region,service,'aws4_request'))
    to_sign='AWS4-HMAC-SHA256\n'+stamp+'\n'+scope+'\n'+hashlib.sha256(canonical.encode()).hexdigest()
    key=('AWS4'+credentials['secret_access_key']).encode()
    for part in (day,region,service,'aws4_request'):key=hmac.new(key,part.encode(),hashlib.sha256).digest()
    signature=hmac.new(key,to_sign.encode(),hashlib.sha256).hexdigest()
    headers['Authorization']='AWS4-HMAC-SHA256 Credential='+credentials['access_key_id']+'/'+scope+', SignedHeaders='+';'.join(keys)+', Signature='+signature
    return Request('https://'+host+path,data=body,headers=headers,method=method)

def upload(config,credentials,key,path,opener=urlopen):
    body=Path(path).read_bytes();checksum=base64.b64encode(hashlib.sha256(body).digest()).decode()
    host=config['bucket']+'.s3.'+config['region']+'.amazonaws.com'
    request=signed_request('s3',config['region'],host,'PUT','/'+quote(key,safe='/'),body,credentials,{'x-amz-server-side-encryption':'AES256','x-amz-checksum-sha256':checksum,'content-type':'application/pkcs7-mime'})
    with opener(request,timeout=60) as response:
        if response.status!=200:raise RuntimeError('s3_upload_failed')
        if response.headers.get('x-amz-checksum-sha256')!=checksum:raise RuntimeError('s3_checksum_mismatch')
        version=response.headers.get('x-amz-version-id')
        if not version or version=='null':raise RuntimeError('s3_versioning_required')
        return {'key':key,'version_id':version,'sha256':hashlib.sha256(body).hexdigest()}

def metric(config,credentials,value,opener=urlopen):
    body=urlencode({'Action':'PutMetricData','Version':'2010-08-01','Namespace':'Kiwoom/Backup','MetricData.member.1.MetricName':'BackupSuccess','MetricData.member.1.Value':value,'MetricData.member.1.Unit':'Count','MetricData.member.1.Dimensions.member.1.Name':'Instance','MetricData.member.1.Dimensions.member.1.Value':'example-server'}).encode()
    host='monitoring.'+config['region']+'.amazonaws.com'
    request=signed_request('monitoring',config['region'],host,'POST','/',body,credentials,{'content-type':'application/x-www-form-urlencoded; charset=utf-8'})
    with opener(request,timeout=20) as response:
        if response.status!=200:raise RuntimeError('backup_metric_failed')

def object_keys(now):
    local=now.astimezone(ZoneInfo('Asia/Seoul'));uid=now.strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex+'.cms'
    keys=['hourly/'+local.strftime('%Y/%m/%d/')+uid]
    if local.hour==1:
        keys.append('daily/'+local.strftime('%Y/%m/%d/')+uid)
        if local.day==1:keys.append('monthly/'+local.strftime('%Y/%m/')+uid)
    return keys

def write_status(path,value):
    path=Path(path);tmp=path.with_suffix('.next');tmp.write_text(json.dumps(value,sort_keys=True));os.chown(tmp,-1,path.parent.stat().st_gid);tmp.chmod(0o640);tmp.replace(path)

def run(config):
    os.umask(0o077)
    credentials={}
    now=dt.datetime.now(dt.timezone.utc);status_path=Path(config['status_path'])
    try:prior=json.loads(status_path.read_text()) if status_path.exists() else {}
    except (OSError,ValueError):prior={}
    try:
        credentials=json.loads(Path(config['credentials']).read_text())
        with tempfile.TemporaryDirectory(prefix='kiwoom-db-backup-',dir=config.get('temporary_directory')) as directory:
            archive,manifest=snapshot(config['state_directory'],directory,now)
            encrypted=Path(directory)/'backup.cms';encrypt(archive,config['certificate'],encrypted)
            results=[upload(config,credentials,key,encrypted) for key in object_keys(now)]
            metric(config,credentials,1)
            status={'ok':True,'last_attempt':now.isoformat(),'last_success':dt.datetime.now(dt.timezone.utc).isoformat(),'objects':results,'database_count':len(manifest['databases'])}
            write_status(status_path,status)
            print(json.dumps(status),flush=True)
    except Exception as error:
        status={'ok':False,'last_attempt':now.isoformat(),'last_success':prior.get('last_success'),'error_type':type(error).__name__}
        write_status(status_path,status)
        try:metric(config,credentials,0)
        except Exception:pass
        print(json.dumps(status),flush=True)
        raise RuntimeError('database_backup_failed') from None

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--config',required=True);args=parser.parse_args()
    run(json.loads(Path(args.config).read_text()))
