"""Personal Kakao OAuth and read-only automatic-fill notifications."""
import contextlib, datetime as dt, fcntl, json, os, re, secrets, sqlite3, time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
DB = Path('/opt/kiwoom/state/kakao-notifications.sqlite3')
TRADES = Path('/opt/kiwoom/state/auto-trading.sqlite3')
SIGNALS = Path('/opt/kiwoom/state/signal-validation.sqlite3')
SITE = 'https://example.invalid/'
NAMES = dict(trend='추세추종', breakout='돌파매매', pullback='눌림목', reversion='평균회귀', momentum='모멘텀')
class KakaoError(ValueError): pass

@contextlib.contextmanager
def locked(path=DB):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(str(path)+'.lock',os.O_CREAT|os.O_RDWR,0o600)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX)
        old=os.umask(0o077)
        try: db=sqlite3.connect(path,timeout=10)
        finally: os.umask(old)
        path.chmod(0o600);db.row_factory=sqlite3.Row
        db.executescript('CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL); CREATE TABLE IF NOT EXISTS cursors (intent INTEGER PRIMARY KEY, qty INTEGER NOT NULL); CREATE TABLE IF NOT EXISTS queue (id INTEGER PRIMARY KEY, intent INTEGER, qty INTEGER, text TEXT, status TEXT, attempts INTEGER DEFAULT 0, due REAL DEFAULT 0, at TEXT, UNIQUE(intent,qty));')
        try: yield db
        finally: db.close()
    finally: os.close(fd)
def load(db):
    r=db.execute('SELECT data FROM settings WHERE id=1').fetchone()
    return json.loads(r['data']) if r else {}
def save(db,c):
    db.execute('INSERT OR REPLACE INTO settings VALUES(1,?)',(json.dumps(c),));db.commit()
def api(url,form=None,token=None):
    headers={}
    if token: headers['Authorization']='Bearer '+token
    data=urlencode(form).encode() if form is not None else None
    if data is not None: headers['Content-Type']='application/x-www-form-urlencoded;charset=utf-8'
    try:
        with urlopen(Request(url,data=data,headers=headers),timeout=12) as r: return json.load(r)
    except HTTPError as e:
        # Do not log response bodies: they may contain credentials.
        if e.code==401: raise KakaoError('kakao_reconnect_required') from None
        if e.code==429: raise KakaoError('kakao_rate_limited') from None
        raise KakaoError('kakao_request_rejected') from None
    except (URLError,TimeoutError,OSError): raise KakaoError('kakao_delivery_unconfirmed') from None

def fill_rows(path=TRADES):
    with sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True,timeout=5) as db:
        db.row_factory=sqlite3.Row
        return [dict(r) for r in db.execute('SELECT id,market,strategy,payload,applied,filled,average,updated FROM intents ORDER BY id')]
def baseline(db,trades,signals=SIGNALS):
    db.execute('DELETE FROM cursors');db.execute('DELETE FROM queue')
    for r in fill_rows(trades): db.execute('INSERT INTO cursors VALUES(?,?)',(r['id'],r['applied']))
    virtual_baseline(db,signals)
    db.commit()
def token_update(c,v,now):
    if not v.get('access_token') or not isinstance(v.get('expires_in'),int): raise KakaoError('kakao_invalid_token_response')
    c['access_token']=v['access_token'];c['expires_at']=now+v['expires_in']
    if v.get('refresh_token'): c['refresh_token']=v['refresh_token']
    if v.get('refresh_token_expires_in'): c['refresh_expires_at']=now+v['refresh_token_expires_in']
def token(db,c,call=api,now=None):
    now=now or time.time()
    if c.get('expires_at',0)>now+120:return c['access_token']
    if not c.get('refresh_token') or c.get('refresh_expires_at',0)<=now: raise KakaoError('kakao_reconnect_required')
    form=dict(grant_type='refresh_token',client_id=c['client_id'],refresh_token=c['refresh_token'])
    if c.get('client_secret'):form['client_secret']=c['client_secret']
    token_update(c,call('https://kauth.kakao.com/oauth/token',form),now);save(db,c)
    return c['access_token']
def public(db,c):
    latest=db.execute("SELECT at FROM queue WHERE status='sent' ORDER BY id DESC LIMIT 1").fetchone()
    pending=db.execute("SELECT COUNT(*) FROM queue WHERE status IN ('pending','retry')").fetchone()[0]
    uncertain=db.execute("SELECT COUNT(*) FROM queue WHERE status IN ('sending','uncertain')").fetchone()[0]
    return dict(configured=bool(c.get('client_id')),connected=bool(c.get('connected')),error=c.get('error'),last_sent=latest['at'] if latest else None,pending=pending,uncertain=uncertain,redirect_uri=SITE)
def send(db,c,text,call=api):
    t=token(db,c,call)
    template=dict(object_type='text',text=text[:1000],link=dict(web_url=SITE,mobile_web_url=SITE),button_title='대시보드 보기')
    v=call('https://kapi.kakao.com/v2/api/talk/memo/default/send',dict(template_object=json.dumps(template,ensure_ascii=False)),t)
    if v.get('result_code')!=0:raise KakaoError('kakao_request_rejected')
def control(body,path=DB,trades=TRADES,call=api,now=None,signals=SIGNALS):
    now=now or time.time();action=body.get('action','status')
    with locked(path) as db:
        c=load(db)
        if action=='setup':
            key=str(body.get('client_id','')).strip();secret=str(body.get('client_secret','')).strip()
            if not re.fullmatch(r'[a-fA-F0-9]{32}',key) or len(secret)>256:raise KakaoError('kakao_invalid_app_key')
            c=dict(client_id=key,client_secret=secret,connected=False);baseline(db,trades,signals);save(db,c)
        elif action=='authorize':
            if not c.get('client_id'):raise KakaoError('kakao_app_setup_required')
            c['state']=secrets.token_urlsafe(32);c['state_expires']=now+600;save(db,c)
            return dict(url='https://kauth.kakao.com/oauth/authorize?'+urlencode(dict(client_id=c['client_id'],redirect_uri=SITE,response_type='code',scope='talk_message',state=c['state'])))
        elif action=='exchange':
            state=str(body.get('state',''));code=str(body.get('code',''))
            if not state or not c.get('state') or not secrets.compare_digest(state,c['state']) or c.get('state_expires',0)<now:raise KakaoError('kakao_invalid_state')
            c.pop('state');c.pop('state_expires',None);save(db,c)
            if not code or len(code)>1024:raise KakaoError('kakao_invalid_code')
            form=dict(grant_type='authorization_code',client_id=c['client_id'],redirect_uri=SITE,code=code)
            if c.get('client_secret'):form['client_secret']=c['client_secret']
            v=call('https://kauth.kakao.com/oauth/token',form)
            if 'talk_message' not in str(v.get('scope','')).split() or not v.get('refresh_token'):raise KakaoError('kakao_message_consent_required')
            token_update(c,v,now);c['connected']=True;c['error']=None;baseline(db,trades,signals);save(db,c)
        elif action=='disconnect':
            c={k:v for k,v in c.items() if k in ('client_id','client_secret')};baseline(db,trades,signals);save(db,c)
        elif action=='test':
            if not c.get('connected'):raise KakaoError('kakao_reconnect_required')
            send(db,c,'[연결 테스트] 실제매매·가상매매 매수·매도 체결 알림이 연결되었습니다. 국내·미국 시장에 적용됩니다.',call)
        elif action!='status':raise KakaoError('kakao_invalid_action')
        return public(db,c)

def collect(db,rows):
    for r in rows:
        prev=db.execute('SELECT qty FROM cursors WHERE intent=?',(r['id'],)).fetchone();qty=int(r['applied']);old=prev['qty'] if prev else 0
        if qty<=old or qty!=r['filled']:continue
        p=json.loads(r['payload']);side=p.get('side')
        if side not in ('buy','sell') or not r['average']:continue
        price=float(r['average'])
        if not price>0:continue
        reason=str(p.get('reason') or '')
        label='매수' if side=='buy' else '익절 매도' if reason.startswith('익절') else '손절 매도' if reason.startswith('손절') else '매도'
        text='[실제매매] '+label+' 체결내역\n'+('국내' if r['market']=='KR' else '미국')+' · '+NAMES.get(r['strategy'],r['strategy'])+'\n'+p['name']+' ('+p['code']+')\n이번 체결 '+str(qty-old)+'주 · 주문 누적 '+str(qty)+'주\n누적 평균 체결가 '+format(price,',.4f').rstrip('0').rstrip('.')+('원' if r['market']=='KR' else ' USD')+'\n확인 '+dt.datetime.fromisoformat(r['updated']).astimezone(dt.timezone(dt.timedelta(hours=9))).strftime('%Y-%m-%d %H:%M:%S')+' (한국시간)'
        if side=='sell':text+='\n매도 사유: '+str(p.get('reason') or '사유 기록 없음')
        db.execute("INSERT OR IGNORE INTO queue(intent,qty,text,status) VALUES(?,?,?,'pending')",(r['id'],qty,text))
        db.execute('INSERT OR REPLACE INTO cursors VALUES(?,?)',(r['id'],qty))
    db.commit()
def virtual_baseline(db,path):
    db.execute('CREATE TABLE IF NOT EXISTS virtual_cursor (id INTEGER PRIMARY KEY CHECK(id=1), event INTEGER NOT NULL)')
    latest=0
    if Path(path).exists():
        with sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True,timeout=5) as src:
            latest=src.execute('SELECT COALESCE(MAX(id),0) FROM events').fetchone()[0]
    db.execute('INSERT OR REPLACE INTO virtual_cursor VALUES(1,?)',(latest,))

def collect_virtual(db,path):
    db.execute('CREATE TABLE IF NOT EXISTS virtual_cursor (id INTEGER PRIMARY KEY CHECK(id=1), event INTEGER NOT NULL)')
    cursor=db.execute('SELECT event FROM virtual_cursor WHERE id=1').fetchone()
    if not cursor:
        # First activation skips old virtual history while preserving real cursors/queue.
        virtual_baseline(db,path);db.commit();return
    if not Path(path).exists():return
    with sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True,timeout=5) as src:
        src.row_factory=sqlite3.Row
        rows=src.execute('SELECT id,data,portfolio FROM events WHERE id>? ORDER BY id LIMIT 200',(cursor['event'],)).fetchall()
    for row in rows:
        p=json.loads(row['data']);side=p.get('kind');market='KR' if row['portfolio']>5 else 'US'
        if side not in ('BUY','SELL'):continue
        price=float(p['reference_price']);qty=int(p['quantity'])
        if not price>0 or qty<=0:continue
        at=dt.datetime.fromisoformat(p['at']).astimezone(dt.timezone(dt.timedelta(hours=9))).strftime('%Y-%m-%d %H:%M:%S')
        text='[가상매매] '+('매수' if side=='BUY' else '매도')+' 체결내역\n'+('국내' if market=='KR' else '미국')+' · '+NAMES.get(p['strategy'],p['strategy'])+'\n'+p['name']+' ('+p['code']+')\n'+str(qty)+'주 · 가상 체결가 '+format(price,',.4f').rstrip('0').rstrip('.')+('원' if market=='KR' else ' USD')+'\n'+p.get('reason','')+'\n'+at+' (한국시간)'
        if side=='SELL' and p.get('return_pct') is not None:text+='\n수익률 '+format(float(p['return_pct']),'+.2f')+'%'
        # Negative IDs keep virtual events separate from positive broker intent IDs.
        db.execute("INSERT OR IGNORE INTO queue(intent,qty,text,status) VALUES(?,?,?,'pending')",(-row['id'],qty,text))
    if rows:db.execute('UPDATE virtual_cursor SET event=? WHERE id=1',(rows[-1]['id'],))
    db.commit()

def cycle(path=DB,trades=TRADES,call=api,now=None,signals=SIGNALS):
    now=now or time.time()
    with locked(path) as db:
        c=load(db)
        if not c.get('connected'):return
        db.execute("UPDATE queue SET status='uncertain' WHERE status='sending'");db.commit()
        # Renew even when no trades occur, so the login remains usable.
        if c.get('refresh_retry',0)>now:return
        try: token(db,c,call,now)
        except KakaoError as e:
            c['error']=str(e);c['refresh_retry']=now+60
            if str(e)=='kakao_reconnect_required':c['connected']=False
            save(db,c);return
        c.pop('refresh_retry',None)
        collect(db,fill_rows(trades))
        collect_virtual(db,signals)
        row=db.execute("SELECT * FROM queue WHERE status IN ('pending','retry') AND due<=? ORDER BY id LIMIT 1",(now,)).fetchone()
        if not row:return
        db.execute("UPDATE queue SET status='sending',attempts=attempts+1 WHERE id=?",(row['id'],));db.commit()
        try:
            send(db,c,row['text'],call);status='sent';c['error']=None
        except KakaoError as e:
            c['error']=str(e);status='uncertain' if str(e)=='kakao_delivery_unconfirmed' else 'retry'
            if str(e)=='kakao_reconnect_required':c['connected']=False
        db.execute('UPDATE queue SET status=?,due=?,at=? WHERE id=?',(status,now+min(3600,60*2**min(row['attempts'],6)),dt.datetime.now(dt.timezone.utc).isoformat(),row['id']));save(db,c)
def worker():
    while True:
        try:cycle()
        except Exception:print('kakao_notification_worker_failed',flush=True)
        time.sleep(15)
if __name__=='__main__':worker()
