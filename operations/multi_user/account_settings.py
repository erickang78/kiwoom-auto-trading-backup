"""Account settings presentation and tenant-local secret updates."""

from __future__ import annotations

import html
import contextlib
import struct
import zlib
import json
import os
import re
import secrets
import sqlite3
from pathlib import Path


def account_page(username: str, tenant: dict, has_photo: bool, message: str = "") -> str:
    name = html.escape(username, quote=True)
    notice = '<p role="status">' + html.escape(message) + '</p>' if message else ""
    source = "/account/photo" if has_photo else ""
    if not source:
        try:
            dashboard = (Path(tenant["dashboard_root"]) / "index.html").read_text()
            match = re.search(r'<img\b[^>]*class=["\'][^"\']*\bericgolf-logo\b[^"\']*["\'][^>]*src=["\'](data:image/(?:jpeg|png|webp);base64,[A-Za-z0-9+/=]+)', dashboard)
            if match and len(match.group(1)) <= 524288:
                source = match.group(1)
        except (KeyError, OSError):
            pass
    photo = '<img src="' + html.escape(source, quote=True) + '" alt="현재 프로필 사진" style="width:52px;height:52px;object-fit:cover;border-radius:13px;flex:none">' if source else '<span aria-hidden="true" style="font-size:32px">👤</span>'
    kiwoom = bool(tenant.get("real_credentials_file") and Path(tenant["real_credentials_file"]).is_file())
    upbit = bool(tenant.get("upbit_credentials_file") and Path(tenant["upbit_credentials_file"]).is_file())
    kiwoom_editable = bool(tenant.get("real_credentials_file") and trading_stopped(tenant.get("auto_trading_state_file")))
    kiwoom_enabled = "" if kiwoom_editable else " disabled"
    upbit_enabled = "" if tenant.get("upbit_credentials_file") else " disabled"
    return f'''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>회원정보 수정</title><style>
body{{font-family:system-ui;background:#f2f5f8;color:#142236;margin:0}}main{{max-width:650px;margin:24px auto;padding:0 16px 40px}}section{{background:#fff;border:1px solid #e3e9ef;border-radius:18px;padding:22px;margin:16px 0}}h1{{font-size:26px}}h2{{font-size:19px}}label{{display:block;margin:13px 0 6px}}input,button{{font:inherit;box-sizing:border-box;padding:11px;border-radius:9px}}input{{width:100%;border:1px solid #cdd8e3}}input[type=file]{{padding:9px}}button{{border:0;background:#147a67;color:white;font-weight:700;margin-top:14px;cursor:pointer}}button:disabled{{opacity:.5}}p,small{{color:#59697d;line-height:1.5}}a{{color:#176f62}}.row{{display:flex;align-items:center;gap:16px}}
</style></head><body><main><p><a href="/">← 대시보드</a></p><h1>회원정보 수정</h1>{notice}
<section><div class="row">{photo}<div><strong>{name}</strong><p>프로필 사진은 이 계정에만 표시됩니다.</p></div></div><label for="photo">프로필 사진 변경</label><input id="photo" type="file" accept="image/jpeg,image/png,image/webp"><button id="photo-save" type="button">사진 저장</button><p id="photo-result" role="status"></p><small>JPG·PNG·WebP, 최대 256KB</small></section>
<section id="password"><h2>비밀번호 변경</h2><form method="post" action="/change-password"><label for="current_password">현재 비밀번호</label><input id="current_password" name="current_password" type="password" required autocomplete="current-password"><label for="new_password">새 비밀번호 (10자 이상)</label><input id="new_password" name="new_password" type="password" minlength="10" required autocomplete="new-password"><label for="confirm_password">새 비밀번호 확인</label><input id="confirm_password" name="confirm_password" type="password" minlength="10" required autocomplete="new-password"><button>비밀번호 변경</button></form><small>변경 후 모든 기기에서 다시 로그인해야 합니다.</small></section>
<section><h2>주식계좌 연결 · 키움 실전</h2><p>연결정보: {'저장됨' if kiwoom else '미설정'}. App Key와 App Secret은 화면에 표시하지 않습니다.</p><form method="post" action="/account/credentials"><input type="hidden" name="kind" value="kiwoom-real"><label for="kiwoom_key">App Key</label><input id="kiwoom_key" name="key" type="password" required autocomplete="off"><label for="kiwoom_secret">App Secret</label><input id="kiwoom_secret" name="secret" type="password" required autocomplete="off"><label for="kiwoom_password">현재 로그인 비밀번호</label><input id="kiwoom_password" name="password" type="password" required autocomplete="current-password"><button{kiwoom_enabled}>연결정보 저장</button></form><small>{'자동매매가 실행 중이거나 미처리 주문이 있어 변경할 수 없습니다.' if not kiwoom_editable else '자동매매가 정지된 상태입니다. 새 인증정보는 다음 API 인증부터 사용됩니다.'}</small></section>
<section><h2>업비트 연결 · 조회 전용</h2><p>연결정보: {'저장됨' if upbit else '미설정'}. Access Key와 Secret Key는 화면에 표시하지 않습니다.</p><form method="post" action="/account/credentials"><input type="hidden" name="kind" value="upbit"><label for="upbit_key">Access Key</label><input id="upbit_key" name="key" type="password" required autocomplete="off"><label for="upbit_secret">Secret Key</label><input id="upbit_secret" name="secret" type="password" required autocomplete="off"><label for="upbit_password">현재 로그인 비밀번호</label><input id="upbit_password" name="password" type="password" required autocomplete="current-password"><button{upbit_enabled}>연결정보 저장</button></form><small>업비트 키는 자산 조회 권한만 부여하세요.</small></section>
<section><h2>카카오톡 알림</h2><p id="kakao-status" role="status">연결 상태 확인 중…</p><button type="button" id="kakao-connect">카카오톡 연결</button> <button type="button" id="kakao-disconnect">연결 해제</button><details><summary>카카오 앱 설정 변경</summary><label for="kakao_key">REST API 키</label><input id="kakao_key" type="password" autocomplete="off"><label for="kakao_secret">Client Secret</label><input id="kakao_secret" type="password" autocomplete="off"><label for="kakao_password">현재 로그인 비밀번호 (설정 저장·연결 해제 시)</label><input id="kakao_password" type="password" autocomplete="current-password"><button type="button" id="kakao-save">앱 설정 저장</button></details></section>
<script>const csrf=document.querySelector('form input[name="_csrf"]')?.value||'';const status=document.querySelector('#kakao-status');async function kakao(action,payload={{}}){{try{{const fields=new URLSearchParams({{action,_csrf:csrf,...payload,password:document.querySelector('#kakao_password').value}});const r=await fetch(action==='status'?'/account/kakao/status':'/account/kakao',action==='status'?{{}}:{{method:'POST',body:fields}});const v=await r.json();if(!r.ok)throw Error('카카오 설정을 처리하지 못했습니다.');if(v.url){{location.assign(v.url);return}}status.textContent=v.connected?'카카오톡 연결됨':v.configured?'앱 설정됨 · 카카오톡 연결 필요':'카카오 앱 설정 필요';}}catch(e){{status.textContent=e.message}}}}kakao('status');document.querySelector('#kakao-connect').onclick=()=>kakao('authorize');document.querySelector('#kakao-disconnect').onclick=()=>kakao('disconnect');document.querySelector('#kakao-save').onclick=()=>kakao('setup',{{client_id:document.querySelector('#kakao_key').value.trim(),client_secret:document.querySelector('#kakao_secret').value.trim()}});document.querySelector('#photo-save').onclick=async()=>{{const file=document.querySelector('#photo').files[0],result=document.querySelector('#photo-result');if(!file||file.size>262144){{result.textContent='사진을 선택하거나 256KB 이하 파일을 사용해 주세요.';return}}try{{const r=await fetch('/account/photo',{{method:'POST',headers:{{'Content-Type':file.type,'X-Moa-CSRF':csrf}},body:file}});if(!r.ok)throw Error('사진 저장에 실패했습니다.');location.reload()}}catch(e){{result.textContent=e.message}}}};</script></main></body></html>'''


def save_credentials(path: Path, kind: str, key: str, secret: str) -> None:
    key, secret = key.strip(), secret.strip()
    if not key or not secret or len(key) > 256 or len(secret) > 256 or any(ord(ch) < 32 for ch in key + secret):
        raise ValueError("invalid credentials")
    path = Path(path)
    if not path.is_absolute() or not path.parent.is_dir() or path.is_symlink():
        raise ValueError("invalid credential path")
    if kind not in ("kiwoom-real", "upbit") or path.parent.is_symlink():
        raise ValueError("invalid credential type or parent")
    payload = json.loads(path.read_text()) if path.exists() else {}
    if not isinstance(payload, dict):
        raise ValueError("invalid existing credentials")
    payload.update({"app_key": key, "app_secret": secret} if kind == "kiwoom-real" else {"access_key": key, "secret_key": secret})
    temporary = path.with_name("." + path.name + "." + secrets.token_hex(8))
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(payload, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def trading_stopped(path: str | None) -> bool:
    if not path or not Path(path).is_file():
        return False
    try:
        with sqlite3.connect("file:" + path + "?mode=ro", uri=True, timeout=2) as db:
            enabled = db.execute("SELECT COUNT(*) FROM portfolios WHERE enabled=1").fetchone()[0]
            pending = db.execute("SELECT COUNT(*) FROM intents WHERE status IN ('accepted','partial','unknown','reconcile_error')").fetchone()[0]
            return enabled == 0 and pending == 0
    except sqlite3.Error:
        return False


@contextlib.contextmanager
def stopped_trading(path: str | None):
    if not path or not Path(path).is_file():
        yield False
        return
    db = None
    try:
        # Reserved write lock prevents another process enabling a portfolio
        # between the check and credential replacement. No rows are modified.
        db = sqlite3.connect("file:" + path + "?mode=rw", uri=True, timeout=2)
        db.execute("BEGIN IMMEDIATE")
        enabled = db.execute("SELECT COUNT(*) FROM portfolios WHERE enabled=1").fetchone()[0]
        pending = db.execute("SELECT COUNT(*) FROM intents WHERE status IN ('accepted','partial','unknown','reconcile_error')").fetchone()[0]
    except sqlite3.Error:
        if db is not None:
            db.close()
        yield False
        return
    try:
        yield enabled == 0 and pending == 0
    finally:
        db.rollback()
        db.close()


def image_type(data: bytes) -> str | None:
    if not 12 <= len(data) <= 262144:
        return None
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        offset = 8
        chunks = []
        while offset + 12 <= len(data):
            size = int.from_bytes(data[offset:offset + 4], "big")
            end = offset + 12 + size
            if end > len(data):
                return None
            kind = data[offset + 4:offset + 8]
            body = data[offset + 8:offset + 8 + size]
            if zlib.crc32(kind + body) & 0xffffffff != int.from_bytes(data[end - 4:end], "big"):
                return None
            if not chunks:
                if kind != b"IHDR" or size != 13:
                    return None
                width, height = struct.unpack(">II", body[:8])
                if not 0 < width <= 4096 or not 0 < height <= 4096:
                    return None
            chunks.append(kind)
            offset = end
            if kind == b"IEND":
                return "image/png" if size == 0 and offset == len(data) and b"IDAT" in chunks else None
        return None
    if data.startswith(b"\xff\xd8\xff") and data.endswith(b"\xff\xd9"):
        offset = 2
        dimensions = False
        while offset + 4 <= len(data):
            if data[offset] != 255:
                return None
            marker = data[offset + 1]
            if marker == 255:
                offset += 1
                continue
            size = int.from_bytes(data[offset + 2:offset + 4], "big")
            if size < 2 or offset + 2 + size > len(data):
                return None
            if marker in (0xc0, 0xc1, 0xc2):
                if size < 8:
                    return None
                height, width = struct.unpack(">HH", data[offset + 5:offset + 9])
                dimensions = 0 < width <= 4096 and 0 < height <= 4096
            if marker == 0xda:
                return "image/jpeg" if dimensions and offset + 2 + size < len(data) - 2 else None
            offset += size + 2
        return None
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        if int.from_bytes(data[4:8], "little") + 8 != len(data):
            return None
        offset = 12
        found = False
        while offset + 8 <= len(data):
            kind = data[offset:offset + 4]
            size = int.from_bytes(data[offset + 4:offset + 8], "little")
            end = offset + 8 + size
            if end > len(data):
                return None
            body = data[offset + 8:end]
            if kind == b"VP8 " and len(body) >= 10 and body[3:6] == b"\x9d\x01\x2a":
                width = int.from_bytes(body[6:8], "little") & 0x3fff
                height = int.from_bytes(body[8:10], "little") & 0x3fff
                found = 0 < width <= 4096 and 0 < height <= 4096
            elif kind == b"VP8L" and len(body) >= 5 and body[0] == 0x2f:
                bits = int.from_bytes(body[1:5], "little")
                found = (bits & 0x3fff) + 1 <= 4096 and ((bits >> 14) & 0x3fff) + 1 <= 4096
            offset = end + (size % 2)
        return "image/webp" if found and offset == len(data) else None
    return None
