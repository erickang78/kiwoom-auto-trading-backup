"""Same-origin login and fixed server-side routing to isolated tenant APIs."""

from __future__ import annotations

import http.client
import hmac
import secrets
import importlib.util
import json
import re
import threading
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from shared_auth import SharedAuth


STYLE = '<style>body{font-family:system-ui;background:#f2f5f8;color:#142236;margin:0;display:grid;place-items:center;min-height:100vh}main{box-sizing:border-box;background:white;border-radius:20px;padding:30px;width:min(92vw,420px)}label{display:block;margin:18px 0 7px}input,button{box-sizing:border-box;width:100%;padding:13px;font:inherit;border-radius:10px}input{border:1px solid #cdd8e3}button{margin-top:17px;border:0;background:#147a67;color:white;font-weight:700}p{color:#66758a}</style>'
LOGIN = '<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>키움 자동매매 · 로그인</title>'+STYLE+'<main><h1>키움 자동매매</h1><form method="post" action="/login"><label for="username">사용자 이름</label><input id="username" name="username" required autocomplete="username"><label for="password">비밀번호</label><input id="password" name="password" type="password" required autocomplete="current-password"><button>로그인</button></form></main></html>'
ACTIVATE = '<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>초대 계정 활성화</title>'+STYLE+'<main><h1>초대 계정 활성화</h1><form method="post" action="/activate"><label for="username">사용자 이름</label><input id="username" name="username" required><label for="invite">초대 코드</label><input id="invite" name="invite" required><label for="password">새 비밀번호 (12자 이상)</label><input id="password" name="password" type="password" minlength="12" required autocomplete="new-password"><button>활성화</button></form></main></html>'
CHANGE_PASSWORD = '<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>비밀번호 변경</title>'+STYLE+'<main><h1>비밀번호 변경</h1><form method="post" action="/change-password"><label for="current_password">현재 비밀번호</label><input id="current_password" name="current_password" type="password" required autocomplete="current-password"><label for="new_password">새 비밀번호 (12자 이상)</label><input id="new_password" name="new_password" type="password" minlength="12" required autocomplete="new-password"><button>변경</button></form><p>변경 후 모든 기기에서 다시 로그인해야 합니다.</p><a href="/">돌아가기</a></main></html>'


class SharedGateway:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.config = json.loads((self.root / "config.json").read_text())
        self.origin = self.config["origin"]
        self.port = int(self.config["port"])
        self.tenants = self.config["tenants"]
        if not self.origin.startswith("https://") or self.origin.count("/") != 2 or not 1024 <= self.port <= 65535:
            raise ValueError("invalid shared gateway origin or port")
        for tenant_id, tenant in self.tenants.items():
            if not re.fullmatch(r"[a-z][a-z0-9-]{2,30}", tenant_id):
                raise ValueError("invalid tenant ID")
            if not 1024 <= int(tenant["api_port"]) <= 65535:
                raise ValueError("invalid tenant API port")
            for key in ("dashboard_root", "backend_token_file"):
                if not Path(tenant[key]).is_absolute():
                    raise ValueError("tenant paths must be absolute")
        self.auth = SharedAuth(self.root / "secrets/users.sqlite3")
        self.failures = {}
        self.lock = threading.Lock()

    def tenant_for(self, user):
        return self.tenants.get(user["tenant_id"]) if user else None

    def handler(self):
        app = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def respond(self, code, body=b"", kind="text/html; charset=utf-8", extra=None):
                if isinstance(body, str):
                    body = body.encode()
                csrf_cookie = None
                if isinstance(body, bytes) and kind.startswith("text/html") and b"<form" in body:
                    csrf = self.csrf_cookie()
                    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", csrf):
                        csrf = secrets.token_urlsafe(32)
                    hidden = '<input type="hidden" name="_csrf" value="' + csrf + '">'
                    body = re.sub(rb"(<form\b[^>]*>)", lambda match: match.group(1) + hidden.encode(), body)
                    csrf_cookie = "__Host-moa_csrf=" + csrf + "; Path=/; Secure; HttpOnly; SameSite=Strict"
                self.send_response(code)
                if csrf_cookie:
                    self.send_header("Set-Cookie", csrf_cookie)
                for key, value in {"Content-Type": kind, "Content-Length": str(len(body)), "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer", **(extra or {})}.items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(body)

            def body(self):
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 <= size <= 8192:
                    raise ValueError("request too large")
                return self.rfile.read(size)

            def token(self):
                try:
                    return SimpleCookie(self.headers.get("Cookie", ""))["moa_shared_session"].value
                except (KeyError, ValueError):
                    return ""

            def csrf_cookie(self):
                try:
                    return SimpleCookie(self.headers.get("Cookie", ""))["__Host-moa_csrf"].value
                except (KeyError, ValueError):
                    return ""

            def user(self):
                return app.auth.session_user(self.token())

            def proxy(self, user):
                tenant = app.tenant_for(user)
                if not tenant:
                    return self.respond(503, json.dumps({"error": "tenant_unavailable"}), "application/json")
                if self.command == "POST" and self.headers.get("Origin") != app.origin:
                    return self.respond(403, "Forbidden")
                try:
                    body = self.body() if self.command == "POST" else None
                    bearer = Path(tenant["backend_token_file"]).read_text().strip()
                    headers = {"Authorization": "Bearer " + bearer, "Origin": tenant["backend_origin"]}
                    if self.headers.get("Content-Type"):
                        headers["Content-Type"] = self.headers["Content-Type"]
                    conn = http.client.HTTPConnection("127.0.0.1", int(tenant["api_port"]), timeout=30)
                    try:
                        conn.request(self.command, self.path, body=body, headers=headers)
                        response = conn.getresponse()
                        payload = response.read(1024 * 1024 + 1)
                        if len(payload) > 1024 * 1024:
                            return self.respond(502, "Upstream response too large")
                        self.respond(response.status, payload, response.getheader("Content-Type", "application/json"))
                    finally:
                        conn.close()
                except ValueError:
                    self.respond(400, "Invalid request")
                except (OSError, http.client.HTTPException):
                    self.respond(502, json.dumps({"error": "upstream_unavailable"}), "application/json")

            def backup_status(self, tenant):
                path = tenant.get("backup_status_file")
                if not path or not Path(path).is_file():
                    return self.respond(404, "Not found")
                spec = importlib.util.spec_from_file_location("tenant_backup_status", path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                self.respond(200, json.dumps(module.read_status()), "application/json")

            def do_GET(self):
                path = urlsplit(self.path).path
                if path == "/login":
                    return self.respond(200, LOGIN)
                if path == "/activate":
                    return self.respond(200, ACTIVATE)
                user = self.user()
                if path == "/change-password":
                    return self.respond(200, CHANGE_PASSWORD if user else LOGIN)
                if path == "/v1/backup/status":
                    if not user:
                        return self.respond(401, json.dumps({"error": "login_required"}), "application/json")
                    return self.backup_status(app.tenant_for(user) or {})
                if path.startswith("/v1/"):
                    if not user:
                        return self.respond(401, json.dumps({"error": "login_required"}), "application/json")
                    return self.proxy(user)
                if path not in ("/", "/index.html", "/stock-list.js"):
                    return self.respond(404, "Not found")
                if not user:
                    return self.respond(200 if path == "/" else 401, LOGIN)
                tenant = app.tenant_for(user)
                if not tenant:
                    return self.respond(503, "Tenant unavailable")
                filename = "stock-list.js" if path == "/stock-list.js" else "index.html"
                try:
                    content = (Path(tenant["dashboard_root"]) / filename).read_text()
                    if filename == "index.html":
                        content, count = re.subn(r"(\bTOKEN\s*=\s*)['\"][^'\"]*['\"]", r"\1''", content)
                        if count != 1 or Path(tenant["backend_token_file"]).read_text().strip() in content:
                            return self.respond(500, "Dashboard configuration error")
                        script = tenant.get("extra_script_file")
                        if script and Path(script).is_file():
                            content = content.replace("</body>", "<script>" + Path(script).read_text() + "</script></body>")
                        content = content.replace("</body>", '<div style="text-align:center;padding:20px"><a href="/change-password">비밀번호 변경</a><form action="/logout" method="post"><button type="submit">로그아웃</button></form></div></body>')
                    self.respond(200, content, "text/javascript; charset=utf-8" if filename.endswith(".js") else "text/html; charset=utf-8")
                except OSError:
                    self.respond(503, "Tenant dashboard unavailable")

            def do_POST(self):
                path = urlsplit(self.path).path
                if path.startswith("/v1/"):
                    user = self.user()
                    if not user:
                        return self.respond(401, json.dumps({"error": "login_required"}), "application/json")
                    return self.proxy(user)
                if path not in ("/login", "/activate", "/logout", "/change-password"):
                    return self.respond(404, "Not found")
                origin = self.headers.get("Origin")
                if origin not in (None, "null", app.origin):
                    return self.respond(403, "Forbidden")
                if self.headers.get("Host", "").lower() != urlsplit(app.origin).netloc.lower():
                    return self.respond(403, "Forbidden")
                try:
                    data = parse_qs(self.body().decode())
                    supplied_csrf = data.get("_csrf", [""])[0]
                    cookie_csrf = self.csrf_cookie()
                    valid_csrf = (
                        bool(re.fullmatch(r"[A-Za-z0-9_-]{43}", supplied_csrf))
                        and bool(re.fullmatch(r"[A-Za-z0-9_-]{43}", cookie_csrf))
                        and hmac.compare_digest(supplied_csrf, cookie_csrf)
                    )
                except (UnicodeError, ValueError):
                    return self.respond(400, "Invalid request")
                if not valid_csrf:
                    return self.respond(403, "Forbidden")
                if path == "/logout":
                    app.auth.logout(self.token())
                    return self.respond(303, extra={"Location": "/", "Set-Cookie": "moa_shared_session=; Path=/; Max-Age=0; Secure; HttpOnly; SameSite=Strict"})
                if path == "/change-password":
                    if not self.user():
                        return self.respond(401, LOGIN)
                    try:
                        changed = app.auth.change_password(self.token(), data.get("current_password", [""])[0], data.get("new_password", [""])[0])
                    except (UnicodeError, ValueError):
                        return self.respond(400, "Invalid request")
                    if not changed:
                        return self.respond(401, CHANGE_PASSWORD.replace("<h1>비밀번호 변경</h1>", "<h1>비밀번호 변경</h1><p>현재 비밀번호 또는 새 비밀번호를 확인해 주세요.</p>"))
                    return self.respond(303, extra={"Location": "/", "Set-Cookie": "moa_shared_session=; Path=/; Max-Age=0; Secure; HttpOnly; SameSite=Strict"})
                try:
                    username = data.get("username", [""])[0]
                    password = data.get("password", [""])[0]
                except (UnicodeError, ValueError):
                    return self.respond(400, "Invalid request")
                with app.lock:
                    now = time.time()
                    app.failures = {k: v for k, v in app.failures.items() if now - v[0] < 300}
                    key = (username, self.client_address[0])
                    if app.failures.get(key, (0, 0))[1] >= 10:
                        return self.respond(429, "잠시 후 다시 시도해 주세요.")
                if path == "/activate":
                    if app.auth.activate(username, data.get("invite", [""])[0], password):
                        return self.respond(303, extra={"Location": "/"})
                else:
                    token = app.auth.login(username, password)
                    if token:
                        return self.respond(303, extra={"Location": "/", "Set-Cookie": "moa_shared_session=" + token + "; Path=/; Max-Age=604800; Secure; HttpOnly; SameSite=Strict"})
                with app.lock:
                    when, count = app.failures.get(key, (now, 0))
                    app.failures[key] = (when, count + 1)
                self.respond(401, ACTIVATE if path == "/activate" else LOGIN)

        return Handler

    def serve(self):
        ThreadingHTTPServer(("127.0.0.1", self.port), self.handler()).serve_forever()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    SharedGateway(parser.parse_args().root).serve()
