"""Reviewed SSM rollout helpers. No orders, strategy starts, or credential writes.

prepare() changes only private staging/backup paths and runs isolated synthetic tests.
apply() quiesces existing auto DB writers under their existing submission gate,
backs up and migrates offline, verifies original rows, then resumes original services.
Do not call rollback after the gate is released to the resumed trading worker.
"""
import ast
import contextlib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import sqlite3
import subprocess
import tempfile
import time
import urllib.request
import urllib.error

ROOT=Path('/opt/kiwoom')
CURRENT=ROOT/'current'
PAGE=ROOT/'dashboard-source/dist/index.html'
DB=ROOT/'state/auto-trading.sqlite3'
CONTROL=ROOT/'state/trading-control.sqlite3'
WRITERS=('kiwoom-refresh.service','moa-real-performance.service','moa-auto-trading.service')
UNTOUCHED=('caddy.service','moa-dashboard.service','moa-shared-login.service','moa-signal-validation.service','moa-kakao-notifications.service')
RUNTIME=('auto_trading.py','strategy_budget.py','auto_recovery.py','auto_performance_history.py')
UI='auto-trading-execution-module'


def check(value,reason):
    if not value:raise RuntimeError(reason)


def command(*args):
    p=subprocess.run(args,capture_output=True,text=True,timeout=90)
    check(p.returncode==0,'command_failed:'+args[0])
    return p.stdout


def sha(raw):return hashlib.sha256(raw).hexdigest()


def properties(unit):
    return dict(line.split('=',1) for line in command('systemctl','show',unit,'--property=ActiveState,SubState,UnitFileState,MainPID,FragmentPath,User,WorkingDirectory,ExecStart').splitlines() if '=' in line)


def safe_properties(unit):
    p=properties(unit);p.pop('ExecStart',None);return p


def private_json(path,data):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w') as out:json.dump(data,out,sort_keys=True,indent=2)


def load_module(name,path):
    import sys
    sys.path.insert(0,str(path.parent))
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ui_part(raw):
    marker=('<script id="'+UI+'">').encode()
    check(raw.count(marker)==1,'ui_marker_count')
    start=raw.index(marker)+len(marker);end=raw.index(b'</script>',start)
    return start,end,raw[start:end]


def baseline(payload):
    check(str(CURRENT.resolve())==payload['current'],'current_release_changed')
    for name,expected in payload['expected'].items():
        check(sha((CURRENT/name).read_bytes())==expected,'live_source_changed:'+name)
    check(not (CURRENT/'strategy_budget.py').exists(),'unexpected_budget_helper')
    check(DB.is_file() and not DB.is_symlink(),'unexpected_database_path')
    check(sha(ui_part(PAGE.read_bytes())[2])==payload['ui_before'],'live_ui_changed')


def atomic(path,raw,metadata):
    fd,temp=tempfile.mkstemp(prefix='.'+path.name+'.strategy-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as out:out.write(raw);out.flush();os.fsync(out.fileno())
        os.chmod(temp,metadata['mode']);os.chown(temp,metadata['uid'],metadata['gid'])
        os.replace(temp,path)
        directory=os.open(path.parent,os.O_RDONLY)
        try:os.fsync(directory)
        finally:os.close(directory)
    finally:
        if os.path.exists(temp):os.unlink(temp)


def metadata(path):
    s=path.stat();return dict(uid=s.st_uid,gid=s.st_gid,mode=s.st_mode&0o777)


def prepare(payload):
    baseline(payload)
    stage=ROOT/('.strategy-stage-'+payload['suffix']);backup=ROOT/('.strategy-backup-'+payload['suffix'])
    check(not stage.exists() and not backup.exists(),'staging_path_exists')
    stage.mkdir(mode=0o700);backup.mkdir(mode=0o700)
    account=pwd.getpwnam('ubuntu');os.chown(stage,account.pw_uid,account.pw_gid)
    before={u:safe_properties(u) for u in WRITERS+UNTOUCHED}
    for unit in WRITERS:
        p=properties(unit)
        expected=str(CURRENT/('refresh_api.py' if unit=='kiwoom-refresh.service' else 'auto_performance_history.py' if unit=='moa-real-performance.service' else 'auto_trading.py'))
        check(p['ActiveState']=='active' and expected in p['ExecStart'] and p['WorkingDirectory']==str(CURRENT),'writer_configuration_changed:'+unit)
    original={}
    for name in RUNTIME:
        p=CURRENT/name
        original[name]=metadata(p) if p.exists() else None
        if p.exists():shutil.copy2(p,backup/name);(backup/name).chmod(0o600)
    shutil.copy2(PAGE,backup/'index.html');(backup/'index.html').chmod(0o600)
    original['index.html']=metadata(PAGE)
    for unit in WRITERS:
        fragment=Path(before[unit]['FragmentPath'])
        shutil.copy2(fragment,backup/unit);(backup/unit).chmod(0o600)
    for p in CURRENT.glob('*.py'):
        if not p.is_file():continue
        shutil.copy2(p,stage/p.name)
        (stage/p.name).chmod(0o600);os.chown(stage/p.name,account.pw_uid,account.pw_gid)
    for name,source in {**payload['files'],**payload['tests']}.items():
        check(Path(name).name==name and name.endswith('.py'),'unsafe_stage_name')
        ast.parse(source,filename=name);(stage/name).write_text(source)
        (stage/name).chmod(0o600);os.chown(stage/name,account.pw_uid,account.pw_gid)
    check(set(payload['files'])==set(RUNTIME),'runtime_scope_changed')
    (stage/'ui.js').write_text(payload['ui'])
    staged_hashes={name:sha((stage/name).read_bytes()) for name in RUNTIME+('ui.js',)}
    plan=dict(stage=str(stage),backup=str(backup),original=original,services=before,hashes=staged_hashes,suffix=payload['suffix'],commit=payload['commit'],phase='staged')
    private_json(backup/'plan.json',plan)
    unit='codex-strategy-tests-'+payload['suffix']
    args=['systemd-run','--wait','--collect','--pipe','--unit='+unit,
          '-p','User=ubuntu','-p','Group=ubuntu','-p','PrivateTmp=yes','-p','PrivateNetwork=yes',
          '-p','RestrictAddressFamilies=AF_UNIX','-p','CapabilityBoundingSet=',
          '-p','NoNewPrivileges=yes','-p','ProtectSystem=strict','-p','ProtectHome=yes',
          '-p','MemoryHigh=96M','-p','MemoryMax=128M','-p','CPUQuota=20%','-p','TasksMax=32',
          '-p','InaccessiblePaths='+str(ROOT/'secrets')+' '+str(ROOT/'state'),
          '-p','WorkingDirectory='+str(stage),'-p','RuntimeMaxSec=60',
          '--setenv=PYTHONPATH='+str(stage),'--setenv=PYTHONDONTWRITEBYTECODE=1',
          '/usr/bin/python3','-m','unittest','-q',*payload['test_modules']]
    p=subprocess.run(args,capture_output=True,text=True,timeout=90)
    private_json(backup/'test-result.json',dict(returncode=p.returncode,stdout=p.stdout,stderr=p.stderr))
    os.chown(stage,0,0);stage.chmod(0o700)
    for staged_file in stage.iterdir():
        if staged_file.is_file():os.chown(staged_file,0,0);staged_file.chmod(0o600)
    check(p.returncode==0,'isolated_server_tests_failed')
    tests=re.search(r'Ran (\d+) tests',p.stderr+'\n'+p.stdout)
    check(tests and '\nOK' in p.stderr+'\n'+p.stdout,'test_summary_missing')
    for unit in WRITERS+UNTOUCHED:
        check(safe_properties(unit)['MainPID']==before[unit]['MainPID'],'production_process_changed_during_staging')
    plan['phase']='tests_passed';plan['tests']=int(tests[1]);private_json(backup/'plan.json',plan)
    return dict(phase=plan['phase'],backup=str(backup),stage=str(stage),tests=plan['tests'],commit=payload['commit'],production_unchanged=True)


def open_writers():
    found=[]
    for proc in Path('/proc').glob('[0-9]*'):
        try:
            for fd in (proc/'fd').iterdir():
                try:
                    if str(fd.resolve())!=str(DB):continue
                    info=(proc/'fdinfo'/fd.name).read_text();flags=int(re.search(r'^flags:\s*([0-7]+)',info,re.M)[1],8)
                    if flags&3:found.append(int(proc.name))
                except (OSError,TypeError):continue
        except OSError:continue
    return sorted(set(found))


def columns(db,table):return [r[1] for r in db.execute('PRAGMA table_info('+table+')')]


def rows(db,table,names,order):
    return db.execute('SELECT '+','.join('"'+n+'"' for n in names)+' FROM '+table+' ORDER BY '+order).fetchall()


def snapshot(db):
    return {table:dict(columns=columns(db,table),rows=rows(db,table,columns(db,table),order)) for table,order in [('portfolios','market'),('intents','id'),('intent_failures','intent_id')]}


def verify_original(db,old):
    for row in old['portfolios']['rows']:
        new=db.execute('SELECT '+','.join('"'+n+'"' for n in old['portfolios']['columns'])+' FROM portfolios WHERE market=? AND strategy=?',(row[0],row[1])).fetchone()
        check(new==row,'legacy_portfolio_not_exact')
    for table,order in [('intents','id'),('intent_failures','intent_id')]:
        check(rows(db,table,old[table]['columns'],order)==old[table]['rows'],'ledger_not_exact:'+table)
    check(db.execute('PRAGMA integrity_check').fetchone()[0]=='ok','database_integrity_failed')


def verify_allocations(db,old):
    original={(r[0],r[1]):r for r in old['portfolios']['rows']}
    check(db.execute('SELECT count(*) FROM portfolios').fetchone()[0]==10,'portfolio_count')
    for market in ('KR','US'):
        row=next(r for r in old['portfolios']['rows'] if r[0]==market)
        cap=db.execute('SELECT total_cap,currency FROM market_budgets WHERE market=?',(market,)).fetchone()
        check(cap==(row[4],'KRW' if market=='KR' else 'USD'),'market_cap_not_preserved')
        for strategy,enabled,budget in db.execute('SELECT strategy,enabled,budget FROM portfolios WHERE market=?',(market,)):
            if (market,strategy) not in original:check(enabled==0 and budget=='0','new_strategy_not_inactive_zero')
    check(db.execute("SELECT enabled,budget FROM portfolios WHERE market='KR' AND strategy='breakout'").fetchone()==(1,'2400000'),'legacy_breakout_changed')


def stopped():
    for unit in WRITERS:check(properties(unit)['ActiveState']=='inactive','writer_not_stopped:'+unit)
    check(not open_writers(),'unexpected_open_auto_db_writer')


def http(path,body=None):
    token=(ROOT/'secrets/dashboard-token').read_text().strip()
    headers={'Authorization':'Bearer '+token,'Origin':'https://example.invalid'}
    if body is not None:headers['Content-Type']='application/json'
    request=urllib.request.Request('http://127.0.0.1:8787'+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
    with urllib.request.urlopen(request,timeout=20) as response:return response.status,json.loads(response.read())


def api_smoke():
    flags={};codes={}
    for market in ('KR','US'):
        for strategy in ('trend','breakout','pullback','reversion','momentum'):
            code,data=http('/v1/trading/auto',dict(action='status',market=market,strategy=strategy))
            check(code==200 and data['strategy']==strategy,'selected_api_status_failed')
            check(len(data['performance_history']['series'])==5,'history_five_series_missing')
            flags[market+':'+strategy]=dict(enabled=data['enabled'],budget=data['budget'],positions=len(data['positions']))
            codes[market+':'+strategy]=code
    code,_=http('/v1/market/stock-list');check(code==200,'stock_list_read_failed')
    check(flags['KR:breakout']['enabled'] and flags['KR:breakout']['budget']=='2400000','breakout_api_state_changed')
    for key,data in flags.items():
        if key not in ('KR:breakout','US:trend'):check(not data['enabled'] and data['budget']=='0','new_strategy_api_state_changed')
    return dict(http_codes=codes,stock_list=code,flags=flags)


def apply(payload):
    baseline(payload)
    backup=ROOT/('.strategy-backup-'+payload['suffix']);plan=json.loads((backup/'plan.json').read_text());stage=Path(plan['stage'])
    check(plan['phase']=='tests_passed' and plan['commit']==payload['commit'],'staging_not_ready')
    for name,expected in plan['hashes'].items():check(sha((stage/name).read_bytes())==expected,'staging_changed:'+name)
    gate_module=load_module('strategy_submission_gate',CURRENT/'trading_control.py')
    migration=load_module('strategy_offline_migration',stage/'strategy_budget.py')
    old=None;changed=False;resumed=False;phase='pre_stop';stopped_units=[];smoke=None
    # UI is backed up fresh; unrelated content is carried forward byte-for-byte.
    original_html=PAGE.read_bytes();check(sha(ui_part(original_html)[2])==payload['ui_before'],'live_ui_changed')
    shutil.copy2(PAGE,backup/'index.html');(backup/'index.html').chmod(0o600)
    plan['original']['index.html']=metadata(PAGE)
    try:
        with gate_module.locked(CONTROL):
            for unit in WRITERS:
                check(properties(unit)['MainPID']==plan['services'][unit]['MainPID'],'writer_process_changed')
                stopped_units.append(unit);command('systemctl','stop',unit)
            stopped();phase='quiesced'
            with sqlite3.connect('file:'+str(DB)+'?mode=ro',uri=True) as db:
                check([r[1] for r in db.execute('PRAGMA table_info(portfolios)') if r[5]]==['market'],'unexpected_schema')
                old=snapshot(db)
            migration.migrate_file(DB,backup/'auto-trading.sqlite3')
            changed=True;phase='migrated'
            with sqlite3.connect(DB) as db:
                verify_original(db,old);verify_allocations(db,old)
            for name in RUNTIME:
                atomic(CURRENT/name,(stage/name).read_bytes(),plan['original'][name] or plan['original']['auto_trading.py'])
            start,end,_=ui_part(original_html);updated=original_html[:start]+(stage/'ui.js').read_bytes()+original_html[end:]
            check(updated[:start]==original_html[:start] and updated[start+len((stage/'ui.js').read_bytes()):]==original_html[end:],'unrelated_html_changed')
            atomic(PAGE,updated,plan['original']['index.html']);phase='files_replaced'
            for name in RUNTIME:check(sha((CURRENT/name).read_bytes())==plan['hashes'][name],'runtime_install_hash_failed')
            check(sha(ui_part(PAGE.read_bytes())[2])==plan['hashes']['ui.js'],'ui_install_hash_failed')
            private_json(backup/'offline-validation.json',dict(portfolio_exact=True,intents_exact=True,intent_failures_exact=True,intents_count=len(old['intents']['rows']),integrity='ok',kr_cap='2400000',new_strategies_disabled_zero=True,html_outside_module_exact=True,commit=payload['commit']))
        # Read-only status checks run while the trading and performance workers remain stopped.
        command('systemctl','start','kiwoom-refresh.service');phase='api_started'
        for _ in range(40):
            try:smoke=api_smoke();break
            except (OSError,urllib.error.URLError):time.sleep(.25)
        check(smoke is not None,'api_not_ready')
        with gate_module.locked(CONTROL):
            with sqlite3.connect('file:'+str(DB)+'?mode=ro',uri=True) as db:verify_original(db,old);verify_allocations(db,old)
            for unit in ('moa-real-performance.service','moa-auto-trading.service'):command('systemctl','start',unit)
            time.sleep(.75)
            for unit in WRITERS:
                check(properties(unit)['ActiveState']=='active' and int(properties(unit)['MainPID'])>0,'service_resume_failed:'+unit)
                check(properties(unit)['UnitFileState']==plan['services'][unit]['UnitFileState'],'service_enabled_state_changed')
            for unit in UNTOUCHED:
                now=safe_properties(unit);before=plan['services'][unit]
                check(now['MainPID']==before['MainPID'] and now['ActiveState']==before['ActiveState'] and now['UnitFileState']==before['UnitFileState'],'untouched_service_changed:'+unit)
            phase='ready_to_resume';private_json(backup/'result.json',dict(phase=phase,smoke=smoke,commit=payload['commit'],backup=str(backup)))
            resumed=True  # Releasing this gate resumes ONLY the already enabled legacy worker.
        phase='deployed'
        result=dict(phase=phase,commit=payload['commit'],backup=str(backup),tests=plan['tests'],changed_files=list(RUNTIME)+['index.html:'+UI],smoke=smoke,legacy_exact_before_resume=True,services={u:dict(active=safe_properties(u)['ActiveState'],enabled=safe_properties(u)['UnitFileState']) for u in WRITERS+UNTOUCHED},no_new_strategy_start=True)
        plan['phase']=phase;private_json(backup/'plan.json',plan);private_json(backup/'result.json',result)
        shutil.rmtree(stage)
        return result
    except Exception as error:
        rollback='not_needed'
        if not resumed:
            with gate_module.locked(CONTROL):
                for unit in WRITERS:
                    if unit in stopped_units:command('systemctl','stop',unit)
                if changed:
                    with sqlite3.connect('file:'+str(DB)+'?mode=ro',uri=True) as db:verify_original(db,old)
                    stopped()
                    migration.restore_file(DB,backup/'auto-trading.sqlite3')
                    for name in RUNTIME:
                        saved=backup/name
                        if plan['original'][name] is None:
                            if (CURRENT/name).exists():(CURRENT/name).unlink()
                        else:atomic(CURRENT/name,saved.read_bytes(),plan['original'][name])
                    atomic(PAGE,(backup/'index.html').read_bytes(),plan['original']['index.html']);rollback='restored_before_resume'
                for unit in stopped_units:
                    if plan['services'][unit]['ActiveState']=='active':command('systemctl','start',unit)
        else:
            # Never discard fills/orders after resumption. Stop submissions for reviewed recovery.
            with gate_module.locked(CONTROL):command('systemctl','stop','moa-auto-trading.service')
            rollback='blocked_after_resume_preserving_ledger'
        private_json(backup/'failure.json',dict(phase=phase,error_type=type(error).__name__,rollback=rollback))
        raise RuntimeError('deployment_failed:'+phase+':'+rollback) from None


def run(mode,payload):
    return prepare(payload) if mode=='prepare' else apply(payload) if mode=='apply' else (_ for _ in ()).throw(ValueError('invalid_mode'))
