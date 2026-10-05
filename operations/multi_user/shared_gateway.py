"""Same-origin login and fixed server-side routing to isolated tenant APIs."""

from __future__ import annotations

import http.client
import hmac
import os
import secrets
import importlib.util
import json
import re
import threading
import time
from email import policy
from email.parser import BytesParser
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from shared_auth import SharedAuth
from account_settings import account_page, image_type, save_credentials, trading_stopped, stopped_trading


STYLE = '<style>body{font-family:system-ui;background:#f2f5f8;color:#142236;margin:0;display:grid;place-items:center;min-height:100vh}main{box-sizing:border-box;background:white;border-radius:20px;padding:30px;width:min(92vw,420px)}label{display:block;margin:18px 0 7px}input,button{box-sizing:border-box;width:100%;padding:13px;font:inherit;border-radius:10px}input{border:1px solid #cdd8e3}button{margin-top:17px;border:0;background:#147a67;color:white;font-weight:700}p{color:#66758a}</style>'
LOGIN = '<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>키움 자동매매 · 로그인</title>'+STYLE+'<main><h1>키움 자동매매</h1><form method="post" action="/login"><label for="username">사용자 이름</label><input id="username" name="username" required autocomplete="username"><label for="password">비밀번호</label><input id="password" name="password" type="password" required autocomplete="current-password"><button>로그인</button></form><p><a href="/signup">초대받아 회원가입하기</a></p></main></html>'
SIGNUP = '<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>키움 자동매매 · 회원가입</title>'+STYLE+'<main><h1>회원가입</h1><p>관리자에게 받은 초대 코드로 가입하고 로그인 ID를 직접 정합니다.</p><form method="post" action="/signup" enctype="multipart/form-data"><label for="invite">초대 코드</label><input id="invite" name="invite" required autocomplete="off"><label for="username">사용할 ID</label><input id="username" name="username" pattern="[a-z][a-z0-9-]{2,30}" minlength="3" maxlength="31" required autocomplete="username"><p>영문 소문자로 시작하는 3~31자의 영문 소문자·숫자·-</p><label for="password">비밀번호 (10자 이상)</label><input id="password" name="password" type="password" minlength="10" required autocomplete="new-password"><label for="confirm_password">비밀번호 확인</label><input id="confirm_password" name="confirm_password" type="password" minlength="10" required autocomplete="new-password"><label for="photo">프로필 사진 (선택)</label><input id="photo" name="photo" type="file" accept="image/jpeg,image/png,image/webp"><div id="photo-preview-wrap" hidden style="margin-top:12px"><img id="photo-preview" alt="선택한 프로필 사진 미리보기" style="width:88px;height:88px;object-fit:cover;border-radius:16px"><p id="photo-name"></p></div><p id="photo-error" role="alert"></p><small>JPG·PNG·WebP, 최대 256KB</small><button>회원가입</button></form><p><a href="/login">로그인으로 돌아가기</a></p></main><script>const photoInput=document.querySelector("#photo"),photoPreview=document.querySelector("#photo-preview"),photoWrap=document.querySelector("#photo-preview-wrap"),photoName=document.querySelector("#photo-name"),photoError=document.querySelector("#photo-error");let photoUrl;photoInput.addEventListener("change",()=>{if(photoUrl)URL.revokeObjectURL(photoUrl);photoUrl=undefined;photoPreview.removeAttribute("src");photoWrap.hidden=true;photoError.textContent="";const file=photoInput.files[0];if(!file)return;if(!["image/jpeg","image/png","image/webp"].includes(file.type)||file.size>262144){photoInput.value="";photoError.textContent="JPG·PNG·WebP 사진을 256KB 이하로 선택해 주세요.";return}photoUrl=URL.createObjectURL(file);photoPreview.src=photoUrl;photoName.textContent=file.name;photoWrap.hidden=false});</script></html>'


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
            for key in ("real_credentials_file", "upbit_credentials_file"):
                if tenant.get(key) and not Path(tenant[key]).is_absolute():
                    raise ValueError("tenant credential paths must be absolute")
        token_paths = [Path(t["backend_token_file"]).resolve() for t in self.tenants.values()]
        if len(token_paths) != len(set(token_paths)) or (self.root / "secrets/users.sqlite3").resolve() in token_paths:
            raise ValueError("tenant token files overlap another tenant or auth database")
        credential_paths = []
        protected = {(self.root / "secrets/users.sqlite3").resolve()}
        protected.update(Path(t["backend_token_file"]).resolve() for t in self.tenants.values())
        for tenant in self.tenants.values():
            for key in ("real_credentials_file", "upbit_credentials_file"):
                if tenant.get(key):
                    path = Path(tenant[key])
                    if path.resolve() in protected or path.resolve() in credential_paths or path.parent.is_symlink():
                        raise ValueError("credential path overlaps protected or another tenant file")
                    credential_paths.append(path.resolve())
            if tenant.get("auto_trading_state_file") and not Path(tenant["auto_trading_state_file"]).is_absolute():
                raise ValueError("trading state path must be absolute")
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

            def body(self, limit=8192):
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 <= size <= limit:
                    raise ValueError("request too large")
                data = self.rfile.read(size)
                if len(data) != size:
                    raise ValueError("incomplete request")
                return data

            def form(self, path):
                content_type = self.headers.get("Content-Type", "")
                if path not in ("/signup", "/activate") or not content_type.startswith("multipart/form-data;"):
                    return parse_qs(self.body().decode()), None
                if "\r" in content_type or "\n" in content_type or len(content_type) > 200:
                    raise ValueError("invalid multipart header")
                envelope = ("Content-Type: " + content_type + "\r\nMIME-Version: 1.0\r\n\r\n").encode() + self.body(300000)
                message = BytesParser(policy=policy.default).parsebytes(envelope)
                if not message.is_multipart() or len(message.get_payload()) > 7:
                    raise ValueError("invalid multipart body")
                fields = {}
                photo = None
                for part in message.iter_parts():
                    if part.get_content_disposition() != "form-data":
                        raise ValueError("invalid multipart part")
                    name = part.get_param("name", header="content-disposition")
                    value = part.get_payload(decode=True)
                    if name == "photo":
                        if photo is not None or value is None or len(value) > 262144:
                            raise ValueError("invalid photo")
                        if value:
                            if image_type(value) != part.get_content_type():
                                raise ValueError("invalid photo")
                            photo = value
                    elif name in ("_csrf", "invite", "username", "password", "confirm_password"):
                        if name in fields or value is None or len(value) > 2048:
                            raise ValueError("invalid form field")
                        fields[name] = [value.decode("utf-8")]
                    else:
                        raise ValueError("unexpected form field")
                return fields, photo

            def photo_file(self, user):
                return app.root / "secrets" / "photos" / (user["tenant_id"] + ".image")

            def save_photo(self, user, data):
                target = self.photo_file(user)
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                temporary = target.with_name(target.name + "." + secrets.token_hex(8))
                fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                try:
                    with os.fdopen(fd, "wb") as handle:
                        handle.write(data)
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(temporary, target)
                finally:
                    temporary.unlink(missing_ok=True)

            def account(self, user, message="", code=200):
                tenant = app.tenant_for(user)
                if not tenant:
                    return self.respond(503, "Tenant unavailable")
                return self.respond(code, account_page(user["username"], tenant, self.photo_file(user).is_file(), message))

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

            def proxy(self, user, kakao_payload=None):
                tenant = app.tenant_for(user)
                if not tenant:
                    return self.respond(503, json.dumps({"error": "tenant_unavailable"}), "application/json")
                if self.command == "POST" and kakao_payload is None and self.headers.get("Origin") != app.origin:
                    return self.respond(403, "Forbidden")
                try:
                    body = json.dumps(kakao_payload).encode() if kakao_payload is not None else self.body() if self.command == "POST" else None
                    bearer = Path(tenant["backend_token_file"]).read_text().strip()
                    headers = {"Authorization": "Bearer " + bearer, "Origin": tenant["backend_origin"]}
                    if kakao_payload is not None:
                        headers["Content-Type"] = "application/json"
                    elif self.headers.get("Content-Type"):
                        headers["Content-Type"] = self.headers["Content-Type"]
                    conn = http.client.HTTPConnection("127.0.0.1", int(tenant["api_port"]), timeout=30)
                    try:
                        conn.request("POST" if kakao_payload is not None else self.command, "/v1/notifications/kakao" if kakao_payload is not None else self.path, body=body, headers=headers)
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
                    query = parse_qs(urlsplit(self.path).query)
                    message = '<p role="status">회원가입이 완료됐습니다. 로그인해 주세요.</p>' if query.get("registered") == ["1"] else ""
                    if query.get("photo") == ["failed"]:
                        message += '<p role="alert">사진 저장에 실패했습니다. 로그인 후 회원정보에서 다시 등록해 주세요.</p>'
                    return self.respond(200, LOGIN.replace("<h1>키움 자동매매</h1>", "<h1>키움 자동매매</h1>" + message))
                if path in ("/signup", "/activate"):
                    return self.respond(200, SIGNUP)
                user = self.user()
                if path == "/change-password":
                    return self.account(user) if user else self.respond(401, LOGIN)
                if path == "/account/kakao/status":
                    return self.proxy(user, {"action": "status"}) if user else self.respond(401, "Login required")
                if path == "/account":
                    return self.account(user) if user else self.respond(401, LOGIN)
                if path == "/account/photo":
                    if not user:
                        return self.respond(401, "Login required")
                    try:
                        with self.photo_file(user).open("rb") as photo:
                            data = photo.read(262145)
                        kind = image_type(data)
                        return self.respond(200, data, kind) if kind else self.respond(404, "Not found")
                    except OSError:
                        return self.respond(404, "Not found")
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
                        profile_script = "<script>(()=>{const img=document.querySelector('img.ericgolf-logo, .logo img');if(!img)return;img.style.cursor='pointer';img.title='회원정보 수정';img.tabIndex=0;img.setAttribute('role','link');img.setAttribute('aria-label','회원정보 수정');img.onclick=()=>location.assign('/account');img.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();location.assign('/account')}};" + ("img.src='/account/photo';" if self.photo_file(user).is_file() else "") + "})();</script>"
                        content = content.replace("</body>", profile_script + "</body>")
                        footer = '''<style>
.gateway-footer{width:min(calc(100% - 32px),760px);margin:18px auto 34px;padding:14px;display:grid;grid-template-columns:repeat(4,minmax(0,1fr));align-items:start;gap:10px;border:1px solid #dce8e5;border-radius:18px;background:#fff;box-shadow:0 12px 35px #18304712;color:#526a76;font:13px/1.4 system-ui,-apple-system,"Apple SD Gothic Neo","Noto Sans KR",sans-serif}
.gateway-footer>a,.gateway-footer>form>button{min-width:0;min-height:46px;display:flex;align-items:center;justify-content:center;padding:10px 12px;border:1px solid #d5e2de;border-radius:11px;background:#f8fbfa;color:#315a59;font:inherit;font-weight:700;text-align:center;text-decoration:none;cursor:pointer;transition:background .15s,border-color .15s,transform .15s}
.gateway-footer>a:hover,.gateway-footer>form>button:hover{border-color:#8fc2b3;background:#eff8f4;transform:translateY(-1px)}
.gateway-footer>a:focus-visible,.gateway-footer>form>button:focus-visible{outline:3px solid #8fc2b388;outline-offset:2px}
.gateway-footer>form{display:contents}
.gateway-footer>form>span{display:flex;min-width:0;width:100%;flex-direction:column;align-items:stretch!important;margin:0!important;vertical-align:initial!important}
.gateway-footer #trading-control{width:100%!important;min-height:46px;margin:0!important;padding:10px 12px!important;border-radius:11px!important;font:inherit!important;font-weight:700!important}
.gateway-footer #trading-control-scope{max-width:none!important;margin:6px 2px 0!important;font-size:10px!important;line-height:1.45!important;text-align:center!important}
.gateway-footer>form>div[role=status]{grid-column:1/-1;margin:2px 4px 0!important;text-align:center}
.gateway-footer .creator-credit{grid-column:1/-1;text-align:center}
@media(max-width:620px){.gateway-footer{width:calc(100% - 28px);margin:14px auto 26px;padding:12px;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px;border-radius:16px}.gateway-footer>a,.gateway-footer>form>button,.gateway-footer #trading-control{min-height:44px;padding:9px 7px!important;font-size:13px!important}.gateway-footer #trading-control-scope{font-size:9px!important}}
</style><div class="gateway-footer"><a href="/account">회원정보 수정</a><a href="/account#password">비밀번호 변경</a><form action="/logout" method="post"><button type="submit">로그아웃</button></form></div>'''
                        content = content.replace("</body>", footer + "</body>")
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
                if path not in ("/login", "/signup", "/activate", "/logout", "/change-password", "/account/credentials", "/account/photo", "/account/kakao"):
                    return self.respond(404, "Not found")
                origin = self.headers.get("Origin")
                if origin not in (None, "null", app.origin):
                    return self.respond(403, "Forbidden")
                if self.headers.get("Host", "").lower() != urlsplit(app.origin).netloc.lower():
                    return self.respond(403, "Forbidden")
                if path == "/account/photo":
                    user = self.user()
                    if not user:
                        return self.respond(401, "Login required")
                    supplied_csrf = self.headers.get("X-Moa-CSRF", "")
                    cookie_csrf = self.csrf_cookie()
                    if not (re.fullmatch(r"[A-Za-z0-9_-]{43}", supplied_csrf) and re.fullmatch(r"[A-Za-z0-9_-]{43}", cookie_csrf) and hmac.compare_digest(supplied_csrf, cookie_csrf)):
                        return self.respond(403, "Forbidden")
                    try:
                        data = self.body(262144)
                        kind = image_type(data)
                        if not kind or kind != self.headers.get("Content-Type"):
                            return self.respond(400, "Invalid image")
                        self.save_photo(user, data)
                        return self.respond(204)
                    except (OSError, ValueError):
                        return self.respond(400, "Invalid image")
                try:
                    data, signup_photo = self.form(path)
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
                if path == "/account/kakao":
                    user = self.user()
                    if not user:
                        return self.respond(401, "Login required")
                    action = data.get("action", [""])[0]
                    if action not in ("setup", "authorize", "disconnect"):
                        return self.respond(400, "Unsupported Kakao action")
                    if action in ("setup", "disconnect") and not app.auth.verify_session_password(self.token(), data.get("password", [""])[0]):
                        return self.respond(401, json.dumps({"error": "password_required"}), "application/json")
                    payload = {"action": action}
                    if action == "setup":
                        payload.update(client_id=data.get("client_id", [""])[0], client_secret=data.get("client_secret", [""])[0])
                    return self.proxy(user, payload)
                if path == "/account/credentials":
                    user = self.user()
                    if not user:
                        return self.respond(401, LOGIN)
                    if not app.auth.verify_session_password(self.token(), data.get("password", [""])[0]):
                        return self.account(user, "현재 로그인 비밀번호를 확인해 주세요.")
                    tenant = app.tenant_for(user) or {}
                    kind = data.get("kind", [""])[0]
                    key = "real_credentials_file" if kind == "kiwoom-real" else "upbit_credentials_file" if kind == "upbit" else None
                    if not key or not tenant.get(key):
                        return self.respond(400, "Unsupported credential type")
                    try:
                        with app.lock:
                            if kind == "kiwoom-real":
                                with stopped_trading(tenant.get("auto_trading_state_file")) as stopped:
                                    if not stopped:
                                        return self.account(user, "자동매매가 실행 중이거나 미처리 주문이 있어 키움 연결정보를 변경할 수 없습니다.")
                                    save_credentials(Path(tenant[key]), kind, data.get("key", [""])[0], data.get("secret", [""])[0])
                            else:
                                save_credentials(Path(tenant[key]), kind, data.get("key", [""])[0], data.get("secret", [""])[0])
                    except (OSError, ValueError):
                        return self.account(user, "연결정보를 저장하지 못했습니다. 값을 확인해 주세요.")
                    return self.respond(303, extra={"Location": "/account"})
                if path == "/logout":
                    app.auth.logout(self.token())
                    return self.respond(303, extra={"Location": "/", "Set-Cookie": "moa_shared_session=; Path=/; Max-Age=0; Secure; HttpOnly; SameSite=Strict"})
                if path == "/change-password":
                    user = self.user()
                    if not user:
                        return self.respond(401, LOGIN)
                    if data.get("new_password", [""])[0] != data.get("confirm_password", [""])[0]:
                        return self.account(user, "새 비밀번호와 확인 값이 일치하지 않습니다.", 400)
                    try:
                        changed = app.auth.change_password(self.token(), data.get("current_password", [""])[0], data.get("new_password", [""])[0])
                    except (UnicodeError, ValueError):
                        return self.respond(400, "Invalid request")
                    if not changed:
                        return self.account(user, "현재 비밀번호 또는 새 비밀번호를 확인해 주세요.", 401)
                    return self.respond(303, extra={"Location": "/login", "Set-Cookie": "moa_shared_session=; Path=/; Max-Age=0; Secure; HttpOnly; SameSite=Strict"})
                try:
                    username = data.get("username", [""])[0]
                    password = data.get("password", [""])[0]
                except (UnicodeError, ValueError):
                    return self.respond(400, "Invalid request")
                with app.lock:
                    now = time.time()
                    app.failures = {k: v for k, v in app.failures.items() if now - v[0] < 300}
                    key = ("signup" if path in ("/signup", "/activate") else username, self.client_address[0])
                    if app.failures.get(key, (0, 0))[1] >= 10:
                        return self.respond(429, "잠시 후 다시 시도해 주세요.")
                if path in ("/signup", "/activate"):
                    if password != data.get("confirm_password", [""])[0]:
                        return self.respond(400, SIGNUP.replace("<h1>회원가입</h1>", "<h1>회원가입</h1><p role='alert'>비밀번호 확인 값이 일치하지 않습니다.</p>"))
                    if app.auth.activate(username, data.get("invite", [""])[0], password):
                        location = "/login?registered=1"
                        if signup_photo:
                            try:
                                with app.auth.connect() as db:
                                    row = db.execute("SELECT tenant_id FROM users WHERE username=? AND enabled=1", (username,)).fetchone()
                                if not row:
                                    raise OSError("activated tenant missing")
                                self.save_photo({"tenant_id": row[0]}, signup_photo)
                            except OSError:
                                location += "&photo=failed"
                        return self.respond(303, extra={"Location": location})
                else:
                    token = app.auth.login(username, password)
                    if token:
                        return self.respond(303, extra={"Location": "/", "Set-Cookie": "moa_shared_session=" + token + "; Path=/; Max-Age=604800; Secure; HttpOnly; SameSite=Strict"})
                with app.lock:
                    when, count = app.failures.get(key, (now, 0))
                    app.failures[key] = (when, count + 1)
                self.respond(401, SIGNUP.replace("<h1>회원가입</h1>", "<h1>회원가입</h1><p role='alert'>초대 정보 또는 비밀번호를 확인해 주세요.</p>") if path in ("/signup", "/activate") else LOGIN)

        return Handler

    def serve(self):
        ThreadingHTTPServer(("127.0.0.1", self.port), self.handler()).serve_forever()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    SharedGateway(parser.parse_args().root).serve()
