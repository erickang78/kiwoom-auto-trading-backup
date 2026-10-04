"""AWS dashboard gateway: protected static UI and same-origin API sessions."""
import hashlib, hmac, http.client, json, secrets, threading, time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
ROOT = Path('/opt/kiwoom/dashboard-source/dist')
KEY = Path('/opt/kiwoom/secrets/dashboard-token').read_text().strip()
ORIGIN = 'https://example.invalid'
OLD_ORIGIN = 'https://moa-invest-sep22.erickang78.chatgpt.site'
TTL = 7*24*3600
FAILURES = {}
LOCK = threading.Lock()
LOGIN = '''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>모아 · 로그인</title><style>body{font-family:system-ui;background:#f2f5f8;color:#142236;margin:0;display:grid;place-items:center;min-height:100vh}main{box-sizing:border-box;background:white;border-radius:24px;padding:32px;width:min(92vw,420px)}h1{margin-top:0}label{display:block;margin:24px 0 8px}input,button{box-sizing:border-box;width:100%;padding:14px;font:inherit;border-radius:12px}input{border:1px solid #cdd8e3}button{margin-top:16px;border:0;background:#147a67;color:white;font-weight:700}p{color:#66758a;line-height:1.6}</style><main><h1>모아 투자 대시보드</h1><p>개인 계좌를 보호하기 위해 접속키로 로그인해 주세요.</p><form method="post" action="/login"><label for="key">접속키</label><input id="key" name="key" type="password" required autocomplete="current-password"><button>로그인</button></form></main></html>'''

def signature(value):
    return hmac.new(KEY.encode(), ('dashboard-session:'+value).encode(), hashlib.sha256).hexdigest()

def session():
    value = str(int(time.time())) + '.' + secrets.token_hex(16)
    return value + '.' + signature(value)

def valid(cookie):
    try:
        jar = SimpleCookie(cookie)
        value, sig = jar['moa_session'].value.rsplit('.',1)
        issued = int(value.split('.')[0])
        return 0 <= time.time()-issued < TTL and hmac.compare_digest(sig, signature(value))
    except Exception:
        return False

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass
    def respond(self, code, body=b'', kind='text/html; charset=utf-8', extra=None):
        if isinstance(body,str): body=body.encode()
        self.send_response(code)
        self.send_header('Content-Type',kind)
        self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        for k,v in (extra or {}).items(): self.send_header(k,v)
        self.end_headers()
        self.wfile.write(body)
    def body(self):
        size=int(self.headers.get('Content-Length','0'))
        if size<0 or size>8192: raise ValueError()
        return self.rfile.read(size)
    def authed(self):
        return valid(self.headers.get('Cookie',''))
    def proxy(self):
        try:
            body=self.body() if self.command=='POST' else None
            headers={k:self.headers[k] for k in ('Authorization','Origin','Content-Type','Access-Control-Request-Headers','Access-Control-Request-Method') if self.headers.get(k)}
            if self.authed():
                if self.command=='POST' and self.headers.get('Origin')!=ORIGIN:
                    return self.respond(403,'Forbidden')
                headers['Authorization']='Bearer '+KEY
                headers['Origin']=OLD_ORIGIN
            conn=http.client.HTTPConnection('127.0.0.1',8787,timeout=90)
            try:
                conn.request(self.command,self.path,body=body,headers=headers)
                r=conn.getresponse()
                payload=r.read()
                extra={k:v for k,v in r.getheaders() if k.lower() in ('access-control-allow-origin','access-control-allow-methods','access-control-allow-headers','vary')}
                self.respond(r.status,payload,r.getheader('Content-Type','application/json'),extra)
            finally: conn.close()
        except ValueError:
            self.respond(400,'Invalid request')
        except Exception:
            self.respond(502,json.dumps({'error':'upstream_unavailable'}),'application/json')
    def do_OPTIONS(self):
        if self.path.startswith('/v1/'): return self.proxy()
        self.respond(404,'Not found')
    def do_GET(self):
        path=urlsplit(self.path).path
        if path=='/v1/backup/status':
            if not self.authed(): return self.respond(401,json.dumps({'error':'unauthorized'}),'application/json')
            from backup_status import read_status
            return self.respond(200,json.dumps(read_status()),'application/json')
        if path.startswith('/v1/') or path=='/health': return self.proxy()
        if path not in ('/','/index.html','/stock-list.js'):
            return self.respond(404,'Not found')
        if not self.authed(): return self.respond(200 if path=='/' else 401,LOGIN)
        filename='stock-list.js' if path=='/stock-list.js' else 'index.html'
        content=(ROOT/filename).read_text()
        if filename=='index.html':
            # The bearer stays on the server, never in the AWS HTML.
            import re
            content,n=re.subn(r"(\bTOKEN\s*=\s*)['\"][^'\"]*['\"]",r"\1''",content)
            if n!=1 or KEY in content: return self.respond(500,'Dashboard configuration error')
            content=content.replace('</body>','<script>'+Path('/opt/kiwoom/backup-tools/dashboard-status.js').read_text()+'</script></body>')
            content=content.replace('</body>','<form action="/logout" method="post" style="text-align:center;padding:20px"><button type="submit">로그아웃</button></form></body>')
        self.respond(200,content,'text/javascript; charset=utf-8' if filename.endswith('.js') else 'text/html; charset=utf-8')
    def do_POST(self):
        if self.path.startswith('/v1/'): return self.proxy()
        if self.path=='/logout':
            if self.headers.get('Origin')!=ORIGIN: return self.respond(403,'Forbidden')
            return self.respond(303,extra={'Location':'/','Set-Cookie':'moa_session=; Path=/; Max-Age=0; Secure; HttpOnly; SameSite=Lax'})
        if self.path!='/login': return self.respond(404,'Not found')
        if self.headers.get('Origin') not in (ORIGIN,'null'):
            return self.respond(403,'Forbidden')
        ip=self.headers.get('X-Forwarded-For',self.client_address[0])
        now=time.time()
        with LOCK:
            for k in list(FAILURES):
                if now-FAILURES[k][0]>300: del FAILURES[k]
            if FAILURES.get(ip,(0,0))[1]>=10: return self.respond(429,'잠시 후 다시 로그인해 주세요.')
        try: supplied=parse_qs(self.body().decode()).get('key',[''])[0]
        except Exception: return self.respond(400,'Invalid request')
        if not hmac.compare_digest(supplied,KEY):
            with LOCK:
                when,count=FAILURES.get(ip,(now,0)); FAILURES[ip]=(when,count+1)
            return self.respond(401,LOGIN.replace('개인 계좌를 보호하기 위해 접속키로 로그인해 주세요.','접속키가 일치하지 않습니다. 다시 입력해 주세요.'))
        self.respond(303,extra={'Location':'/','Set-Cookie':'moa_session='+session()+'; Path=/; Max-Age='+str(TTL)+'; Secure; HttpOnly; SameSite=Lax'})

if __name__=='__main__':
    ThreadingHTTPServer(('127.0.0.1',8788),Handler).serve_forever()
