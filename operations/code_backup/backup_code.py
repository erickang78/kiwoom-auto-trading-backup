"""Daily sanitized production source snapshots to a dedicated GitHub branch."""
import datetime as dt,hashlib,json,os,re,shutil,subprocess,tempfile
from pathlib import Path
from check_repository_secrets import inspect
ROOT=Path('/opt/kiwoom')
REPO=ROOT/'code-backup/repository'
REMOTE='git@github.com:erickang78/kiwoom-auto-trading-backup.git'
BRANCH='server-daily-backup'
STATUS=ROOT/'backup-status/code-status.json'
ENV={**os.environ,'GIT_TERMINAL_PROMPT':'0','GIT_SSH_COMMAND':'ssh -i /opt/kiwoom/secrets/github-backup-key -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=/opt/kiwoom/code-backup/github_known_hosts -o HostKeyAlgorithms=ssh-ed25519'}

def git(*args,cwd=REPO,check=True):
    return subprocess.run(['git',*args],cwd=cwd,env=ENV,check=check,capture_output=True,text=True,timeout=120)

def secret_values(directory):
    values=[]
    def collect(value):
        if isinstance(value,str) and len(value)>=12:values.append(value.encode())
        elif isinstance(value,dict):
            for key,v in value.items():
                if isinstance(v,(dict,list)) or re.search(r'(?i)(secret|password|token|api.?key|access.?key|app.?key)',key):collect(v)
        elif isinstance(value,list):
            for v in value:collect(v)
    for path in Path(directory).iterdir():
        if not path.is_file():continue
        raw=path.read_bytes().strip()
        try:collect(json.loads(raw))
        except (ValueError,UnicodeDecodeError):
            if len(raw)>=12:values.append(raw)
            for line in raw.splitlines():
                if b'=' in line:
                    key,value=line.split(b'=',1)
                    if re.search(rb'(?i)(secret|password|token|api.?key|access.?key|app.?key)',key) and len(value.strip())>=12:values.append(value.strip().strip(b'\"\''))
    return values

def source_files(root=ROOT,system=Path('/etc/systemd/system')):
    files={}
    for path in (root/'current').rglob('*'):
        if path.is_file() and path.suffix in ('.py','.sh','.toml','.ini','.cfg','.txt') and not any(x.startswith('.') or x in ('__pycache__','node_modules','secrets','logs','state') for x in path.relative_to(root/'current').parts):
            files['current/'+str(path.relative_to(root/'current'))]=path
    # Required reference data: these are public symbol catalogues, not account snapshots.
    for name in ('stock-list.json','us-stock-list.json'):
        files['current/'+name]=root/'current'/name
    for path in root.glob('*.py'):files['root/'+path.name]=path
    for path in (root/'dashboard-source/dist').rglob('*'):
        if path.is_file() and path.suffix in ('.html','.js','.css','.svg','.ico') and not any(x.startswith('.') for x in path.relative_to(root/'dashboard-source/dist').parts):
            files['dashboard/dist/'+str(path.relative_to(root/'dashboard-source/dist'))]=path
    for path in (root/'backup-tools').rglob('*'):
        if path.is_file() and path.suffix in ('.py','.js','.crt'):files['backup-tools/'+str(path.relative_to(root/'backup-tools'))]=path
    for pattern in ('moa-*.service','kiwoom-*.service','moa-*.timer','kiwoom-*.timer','kiwoom-*.service.d/*.conf','moa-*.service.d/*.conf'):
        for path in system.glob(pattern):files['config/systemd/'+str(path.relative_to(system))]=path
    files['config/Caddyfile']=Path('/etc/caddy/Caddyfile')
    return files

def capture(files,destination,known):
    manifest=[]
    for name,path in sorted(files.items()):
        if path.is_symlink():raise ValueError('source_symlink_review_required')
        data=path.read_bytes()
        if len(data)>10*1024*1024:raise ValueError('source_size_review_required')
        issues=inspect(name,data,known)
        # Fail closed for common hardcoded credentials, including systemd environments.
        if re.search(rb'(?im)(?:secret|password|access_token|refresh_token|api_key)\s*[=:]\s*[\x27\x22][A-Za-z0-9_./+\-=]{16,}[\x27\x22]',data):issues.append('credential_literal')
        if issues:raise ValueError('source_secret_scan_failed')
        target=destination/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
        manifest.append({'path':name,'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)})
    if not manifest:raise ValueError('empty_source_snapshot')
    (destination/'manifest.json').write_text(json.dumps({'files':manifest,'excluded':['secrets','databases','logs','legacy copies'],'consistency':'file-by-file source snapshot'},indent=2))
    return len(manifest)

def status(value):
    temp=STATUS.with_suffix('.next');temp.write_text(json.dumps(value));os.chown(temp,-1,STATUS.parent.stat().st_gid);temp.chmod(0o640);temp.replace(STATUS)

def run():
    os.umask(0o077);now=dt.datetime.now(dt.timezone.utc).isoformat()
    try:previous=json.loads(STATUS.read_text())
    except (OSError,ValueError):previous={}
    try:
        if not REPO.exists():git('clone','--no-checkout',REMOTE,str(REPO),cwd=REPO.parent)
        git('config','user.name','Kiwoom source backup');git('config','user.email','backup@localhost')
        # Do not run repository hooks or replace other branches.
        git('config','core.hooksPath','/dev/null')
        remote=git('ls-remote','--heads','origin',BRANCH).stdout.strip()
        if remote:
            git('fetch','origin',BRANCH)
            local=git('rev-parse','--verify',BRANCH,check=False)
            if local.returncode:git('checkout','-b',BRANCH,'FETCH_HEAD')
            else:
                git('checkout',BRANCH)
                ahead=git('merge-base','--is-ancestor','FETCH_HEAD','HEAD',check=False)
                if ahead.returncode:git('merge','--ff-only','FETCH_HEAD')
        else:
            local=git('rev-parse','--verify',BRANCH,check=False)
            if local.returncode:git('checkout','-b',BRANCH,'origin/main')
            else:git('checkout',BRANCH)
        known=secret_values(ROOT/'secrets')
        with tempfile.TemporaryDirectory(dir=REPO.parent,prefix='snapshot-') as directory:
            stage=Path(directory);count=capture(source_files(),stage,known)
            target=REPO/'server-daily'
            if target.is_symlink():raise ValueError('snapshot_target_symlink')
            if target.exists():shutil.rmtree(target)  # Replace only this generated local snapshot.
            shutil.copytree(stage,target)
        git('add','-A','--','server-daily')
        # Check all staged content, including inherited repository files, before upload.
        for name in filter(None,git('ls-files','-z').stdout.split('\0')):
            data=subprocess.check_output(['git','show',':'+name],cwd=REPO,env=ENV)
            if inspect(name,data,known):raise ValueError('index_secret_scan_failed')
        changed=git('diff','--cached','--quiet',check=False).returncode
        if changed==1:git('commit','-m','Daily production source backup '+now)
        elif changed!=0:raise RuntimeError('git_diff_failed')
        git('push','origin','HEAD:refs/heads/'+BRANCH)
        commit=git('rev-parse','HEAD').stdout.strip()
        status({'ok':True,'last_attempt':now,'last_success':dt.datetime.now(dt.timezone.utc).isoformat(),'file_count':count,'commit':commit,'changed':bool(changed)})
        print('CODE_BACKUP_OK',count,commit,flush=True)
    except Exception as error:
        status({'ok':False,'last_attempt':now,'last_success':previous.get('last_success'),'error_type':type(error).__name__})
        raise RuntimeError('code_backup_failed; inspect protected local state') from None
if __name__=='__main__':run()
