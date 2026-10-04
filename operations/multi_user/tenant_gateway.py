"""Isolated tenant dashboard gateway with invitation-only account activation."""
import http.client, json, re, threading, time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from tenant_auth import TenantAuth
ROOT = Path('/opt/kiwoom/dashboard-source/dist')
KEY = Path('/opt/kiwoom/secrets/dashboard-token').read_text().strip()
AUTH = TenantAuth(Path('/opt/kiwoom'))
ORIGIN = 'https://example.invalid'
OLD_ORIGIN = 'https://moa-invest-sep22.erickang78.chatgpt.site'
TTL = 7*24*3600
FAILURES = {}
LOCK = threading.Lock()
STYLE = '''<style>body{font-family:system-ui;background:#f2f5f8;color:#142236;margin:0;display:grid;place-items:center;min-height:100vh}main{box-sizing:border-box;background:white;border-radius:24px;padding:32px;width:min(92vw,420px)}h1{margin-top:0}label{display:block;margin:24px 0 8px}input,button{box-sizing:border-box;width:100%;padding:14px;font:inherit;border-radius:12px}input{border:1px solid #cdd8e3}button{margin-top:16px;border:0;background:#147a67;color:white;font-weight:700}p{color:#66758a;line-height:1.6}</style>'''
LOGIN = '<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>키움 자동매매 · 로그인</title>'+STYLE+'<main><h1>키움 자동매매</h1><p>비밀번호로 로그인해 주세요.</p><form method="post" action="/login"><label for="password">비밀번호</label><input id="password" name="password" type="password" required autocomplete="current-password"><button>로그인</button></form></main></html>'
ACTIVATE = '<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>계정 활성화</title>'+STYLE+'<main><h1>계정 활성화</h1><p>관리자에게 받은 일회용 초대 코드와 새 비밀번호를 입력하세요. 비밀번호는 12자 이상이어야 합니다.</p><form method="post" action="/activate"><label for="invite">초대 코드</label><input id="invite" name="invite" required autocomplete="one-time-code"><label for="password">새 비밀번호</label><input id="password" name="password" type="password" minlength="12" required autocomplete="new-password"><button>계정 활성화</button></form></main></html>'

def valid(cookie):
    try:
        jar = SimpleCookie(cookie)
        return AUTH.valid_session(jar['moa_tenant_session'].value, TTL)
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
            if not self.authed(): return self.respond(401,json.dumps({'error':'login_required'}),'application/json')
            body=self.body() if self.command=='POST' else None
            headers={k:self.headers[k] for k in ('Content-Type','Access-Control-Request-Headers','Access-Control-Request-Method') if self.headers.get(k)}
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
        if path.startswith('/v1/') or path=='/health': return self.proxy()
        if path == '/activate': return self.respond(200,ACTIVATE)
        if path not in ('/','/index.html','/stock-list.js'):
            return self.respond(404,'Not found')
        if not self.authed(): return self.respond(200 if path=='/' else 401,LOGIN)
        filename='stock-list.js' if path=='/stock-list.js' else 'index.html'
        content=(ROOT/filename).read_text()
        if filename=='index.html':
            # The bearer stays on the server, never in the AWS HTML.
            content,n=re.subn(r"(\bTOKEN\s*=\s*)['\"][^'\"]*['\"]",r"\1''",content)
            if n!=1 or KEY in content: return self.respond(500,'Dashboard configuration error')
            content=content.replace('</body>','<form action="/logout" method="post" style="text-align:center;padding:20px"><button type="submit">로그아웃</button></form></body>')
        self.respond(200,content,'text/javascript; charset=utf-8' if filename.endswith('.js') else 'text/html; charset=utf-8')
    def do_POST(self):
        if self.path.startswith('/v1/'): return self.proxy()
        if self.path=='/logout':
            if self.headers.get('Origin')!=ORIGIN: return self.respond(403,'Forbidden')
            return self.respond(303,extra={'Location':'/','Set-Cookie':'moa_tenant_session=; Path=/; Max-Age=0; Secure; HttpOnly; SameSite=Strict'})
        if self.path not in ('/login','/activate'): return self.respond(404,'Not found')
        if self.headers.get('Origin') not in (ORIGIN,'null'):
            return self.respond(403,'Forbidden')
        ip=self.headers.get('X-Forwarded-For',self.client_address[0])
        now=time.time()
        with LOCK:
            for k in list(FAILURES):
                if now-FAILURES[k][0]>300: del FAILURES[k]
            if FAILURES.get(ip,(0,0))[1]>=10: return self.respond(429,'잠시 후 다시 로그인해 주세요.')
        try:
            data=parse_qs(self.body().decode())
            supplied=data.get('password',[''])[0]
        except Exception: return self.respond(400,'Invalid request')
        if self.path=='/activate':
            accepted=AUTH.activate(data.get('invite',[''])[0],supplied)
            if accepted: return self.respond(303,extra={'Location':'/'})
        elif AUTH.verify_password(supplied):
            return self.respond(303,extra={'Location':'/','Set-Cookie':'moa_tenant_session='+AUTH.new_session()+'; Path=/; Max-Age='+str(TTL)+'; Secure; HttpOnly; SameSite=Strict'})
        with LOCK:
            when,count=FAILURES.get(ip,(now,0)); FAILURES[ip]=(when,count+1)
        return self.respond(401,ACTIVATE if self.path=='/activate' else LOGIN)

if __name__=='__main__':
    ThreadingHTTPServer(('127.0.0.1',8788),Handler).serve_forever()
