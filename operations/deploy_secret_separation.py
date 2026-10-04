"""Remove the legacy frontend token while retaining existing server-side credentials."""
from pathlib import Path
import datetime, hashlib, http.client, importlib.util, json, os, re, sqlite3, subprocess, time
ROOT=Path('/opt/kiwoom');PAGE=ROOT/'dashboard-source/dist/index.html';GATEWAY=ROOT/'dashboard_gateway.py'

def deploy(payload):
    oldpage=PAGE.read_bytes();oldgateway=GATEWAY.read_bytes()
    assert hashlib.sha256(oldgateway).hexdigest()==payload['gateway_sha']
    assert hashlib.sha256(oldpage).hexdigest()==payload['page_sha']
    keypath=ROOT/'secrets/dashboard-token';key=keypath.read_text().strip();assert key
    pattern=r"(\bTOKEN\s*=\s*)(['\"])([^'\"]*)\2"
    m=re.search(pattern,oldpage.decode());assert m and m[3]==key
    newpage,n=re.subn(pattern,lambda m:m[1]+"''",oldpage.decode());assert n==1 and key not in newpage
    newgateway=payload['gateway'];compile(newgateway,str(GATEWAY),'exec')
    assert key not in newgateway
    # Observe trading configuration and process identity without modifying either.
    def trade_state():
        con=sqlite3.connect('file:/opt/kiwoom/state/auto-trading.sqlite3?mode=ro',uri=True)
        try:return con.execute('SELECT market,strategy,enabled,revision,budget,started FROM portfolios ORDER BY market').fetchall()
        finally:con.close()
    before=trade_state();pid=subprocess.check_output(['systemctl','show','moa-auto-trading','--property=MainPID','--value']).strip()
    backup=ROOT/'backups'/('secret-separation-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ'));backup.mkdir(mode=0o700)
    for name,data in [('index.html',oldpage),('dashboard_gateway.py',oldgateway)]:
        p=backup/name;p.write_bytes(data);p.chmod(0o600)
    def replace(path,data):
        stat=path.stat();tmp=path.with_name(path.name+'.secret-next');tmp.write_bytes(data);os.chmod(tmp,stat.st_mode & 0o777);os.chown(tmp,stat.st_uid,stat.st_gid);tmp.replace(path)
    report={}
    try:
        replace(GATEWAY,newgateway.encode());replace(PAGE,newpage.encode())
        subprocess.run(['systemctl','restart','moa-dashboard'],check=True)
        for _ in range(30):
            try:
                conn=http.client.HTTPConnection('127.0.0.1',8788,timeout=3);conn.request('GET','/index.html');r=conn.getresponse();r.read();conn.close()
                if r.status==401:break
            except OSError:pass
            time.sleep(.2)
        else:raise RuntimeError('gateway_not_ready')
        spec=importlib.util.spec_from_file_location('verify_gateway',GATEWAY);g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g)
        cookie='moa_session='+g.session()
        def request(method,path,body=None,auth=False):
            headers={'Origin':g.ORIGIN,'Content-Type':'application/json'}
            if auth:headers['Cookie']=cookie
            conn=http.client.HTTPConnection('127.0.0.1',8788,timeout=30)
            try:
                conn.request(method,path,body,headers);r=conn.getresponse();data=r.read();return r.status,data
            finally:conn.close()
        code,content=request('GET','/index.html',auth=True)
        assert code==200 and key.encode() not in content and re.search(rb"TOKEN\s*=\s*''",content)
        report['authenticated_page']=code
        report['unauthenticated_source']=request('GET','/index.html')[0];assert report['unauthenticated_source']==401
        for source in ('real','virtual'):
            code,data=request('POST','/v1/trading/auto',json.dumps({'action':'performance','market':'KR','strategy':'trend','report_strategy':'all','report_source':source}),True)
            assert code==200 and isinstance(json.loads(data).get('available'),bool)
            report[source+'_report']=code
        assert trade_state()==before
        assert subprocess.check_output(['systemctl','show','moa-auto-trading','--property=MainPID','--value']).strip()==pid
        assert keypath.read_text().strip()==key
        report.update(trading_config_unchanged=True,trading_worker_not_restarted=True,credential_unchanged=True,frontend_token_removed=True)
        subprocess.run(['systemctl','is-active','moa-dashboard','kiwoom-refresh','moa-auto-trading','moa-signal-validation','moa-kakao-notifications'],check=True)
    except BaseException:
        replace(GATEWAY,oldgateway);replace(PAGE,oldpage);subprocess.run(['systemctl','restart','moa-dashboard']);raise
    (backup/'verification.json').write_text(json.dumps(report,indent=2))
    print('SECRET_SEPARATION_OK',json.dumps(report));print('ROLLBACK_DIRECTORY',backup)
