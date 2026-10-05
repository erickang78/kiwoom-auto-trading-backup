"""Account settings presentation and tenant-local secret updates."""

from __future__ import annotations

import html
import json
import os
import secrets
import sqlite3
from pathlib import Path


def account_page(username: str, tenant: dict, has_photo: bool, message: str = "") -> str:
    name = html.escape(username, quote=True)
    notice = '<p role="status">' + html.escape(message) + '</p>' if message else ""
    photo = '<img src="/account/photo" alt="프로필 사진" style="width:72px;height:72px;object-fit:cover;border-radius:18px">' if has_photo else '<span aria-hidden="true" style="font-size:40px">👤</span>'
    kiwoom = bool(tenant.get("real_credentials_file") and Path(tenant["real_credentials_file"]).is_file())
    upbit = bool(tenant.get("upbit_credentials_file") and Path(tenant["upbit_credentials_file"]).is_file())
    kiwoom_editable = bool(tenant.get("real_credentials_file") and trading_stopped(tenant.get("auto_trading_state_file")))
    kiwoom_enabled = "" if kiwoom_editable else " disabled"
    upbit_enabled = "" if tenant.get("upbit_credentials_file") else " disabled"
    return f'''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>회원정보 수정</title><style>
body{{font-family:system-ui;background:#f2f5f8;color:#142236;margin:0}}main{{max-width:650px;margin:24px auto;padding:0 16px 40px}}section{{background:#fff;border:1px solid #e3e9ef;border-radius:18px;padding:22px;margin:16px 0}}h1{{font-size:26px}}h2{{font-size:19px}}label{{display:block;margin:13px 0 6px}}input,button{{font:inherit;box-sizing:border-box;padding:11px;border-radius:9px}}input{{width:100%;border:1px solid #cdd8e3}}input[type=file]{{padding:9px}}button{{border:0;background:#147a67;color:white;font-weight:700;margin-top:14px;cursor:pointer}}button:disabled{{opacity:.5}}p,small{{color:#59697d;line-height:1.5}}a{{color:#176f62}}.row{{display:flex;align-items:center;gap:16px}}
</style></head><body><main><p><a href="/">← 대시보드</a></p><h1>회원정보 수정</h1>{notice}
<section><div class="row">{photo}<div><strong>{name}</strong><p>프로필 사진은 이 계정에만 표시됩니다.</p></div></div><label for="photo">프로필 사진 변경</label><input id="photo" type="file" accept="image/jpeg,image/png,image/webp"><button id="photo-save" type="button">사진 저장</button><p id="photo-result" role="status"></p><small>JPG·PNG·WebP, 최대 256KB</small></section>
<section><h2>로그인 ID</h2><p>현재 ID: <strong>{name}</strong></p><form method="post" action="/account/username"><label for="new_username">새 ID</label><input id="new_username" name="new_username" pattern="[a-z][a-z0-9-]{{2,30}}" maxlength="31" required autocomplete="off"><label for="id_password">현재 비밀번호</label><input id="id_password" name="password" type="password" required autocomplete="current-password"><button>변경</button></form><small>변경 후 다시 로그인해야 합니다.</small></section>
<section><h2>비밀번호</h2><p>비밀번호는 저장된 값을 표시하지 않습니다.</p><a href="/change-password">비밀번호 변경</a></section>
<section><h2>주식계좌 연결 · 키움 실전</h2><p>연결정보: {'저장됨' if kiwoom else '미설정'}. App Key와 App Secret은 화면에 표시하지 않습니다.</p><form method="post" action="/account/credentials"><input type="hidden" name="kind" value="kiwoom-real"><label for="kiwoom_key">App Key</label><input id="kiwoom_key" name="key" type="password" required autocomplete="off"><label for="kiwoom_secret">App Secret</label><input id="kiwoom_secret" name="secret" type="password" required autocomplete="off"><label for="kiwoom_password">현재 로그인 비밀번호</label><input id="kiwoom_password" name="password" type="password" required autocomplete="current-password"><button{kiwoom_enabled}>연결정보 저장</button></form><small>{'자동매매가 실행 중이거나 미처리 주문이 있어 변경할 수 없습니다.' if not kiwoom_editable else '자동매매가 정지된 상태입니다. 새 인증정보는 다음 API 인증부터 사용됩니다.'}</small></section>
<section><h2>업비트 연결 · 조회 전용</h2><p>연결정보: {'저장됨' if upbit else '미설정'}. Access Key와 Secret Key는 화면에 표시하지 않습니다.</p><form method="post" action="/account/credentials"><input type="hidden" name="kind" value="upbit"><label for="upbit_key">Access Key</label><input id="upbit_key" name="key" type="password" required autocomplete="off"><label for="upbit_secret">Secret Key</label><input id="upbit_secret" name="secret" type="password" required autocomplete="off"><label for="upbit_password">현재 로그인 비밀번호</label><input id="upbit_password" name="password" type="password" required autocomplete="current-password"><button{upbit_enabled}>연결정보 저장</button></form><small>업비트 키는 자산 조회 권한만 부여하세요.</small></section>
<section><h2>카카오톡 알림</h2><p id="kakao-status" role="status">연결 상태 확인 중…</p><button type="button" id="kakao-connect">카카오톡 연결</button> <button type="button" id="kakao-disconnect">연결 해제</button><details><summary>카카오 앱 설정 변경</summary><label for="kakao_key">REST API 키</label><input id="kakao_key" type="password" autocomplete="off"><label for="kakao_secret">Client Secret</label><input id="kakao_secret" type="password" autocomplete="off"><button type="button" id="kakao-save">앱 설정 저장</button></details></section>
<section><h2>내부 API key</h2><p>기존 대시보드 key는 서버 내부 API 인증용입니다. 로그인 비밀번호와 분리되어 있으며 이 화면에 표시하지 않습니다.</p></section>
<script>const csrf=document.querySelector('form input[name="_csrf"]')?.value||'';const status=document.querySelector('#kakao-status');async function kakao(action,payload={{}}){{try{{const r=await fetch('/v1/notifications/kakao',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{action,...payload}})}});const v=await r.json();if(!r.ok)throw Error('카카오 설정을 처리하지 못했습니다.');if(v.url){{location.assign(v.url);return}}status.textContent=v.connected?'카카오톡 연결됨':v.configured?'앱 설정됨 · 카카오톡 연결 필요':'카카오 앱 설정 필요';}}catch(e){{status.textContent=e.message}}}}kakao();document.querySelector('#kakao-connect').onclick=()=>kakao('authorize');document.querySelector('#kakao-disconnect').onclick=()=>kakao('disconnect');document.querySelector('#kakao-save').onclick=()=>kakao('setup',{{client_id:document.querySelector('#kakao_key').value.trim(),client_secret:document.querySelector('#kakao_secret').value.trim()}});document.querySelector('#photo-save').onclick=async()=>{{const file=document.querySelector('#photo').files[0],result=document.querySelector('#photo-result');if(!file||file.size>262144){{result.textContent='사진을 선택하거나 256KB 이하 파일을 사용해 주세요.';return}}try{{const r=await fetch('/account/photo',{{method:'POST',headers:{{'Content-Type':file.type,'X-Moa-CSRF':csrf}},body:file}});if(!r.ok)throw Error('사진 저장에 실패했습니다.');location.reload()}}catch(e){{result.textContent=e.message}}}};</script></main></body></html>'''


def save_credentials(path: Path, kind: str, key: str, secret: str) -> None:
    if not key or not secret or len(key) > 256 or len(secret) > 256 or any(ord(ch) < 32 for ch in key + secret):
        raise ValueError("invalid credentials")
    path = Path(path)
    if not path.is_absolute() or not path.parent.is_dir() or path.is_symlink():
        raise ValueError("invalid credential path")
    payload = {"app_key": key, "app_secret": secret} if kind == "kiwoom-real" else {"access_key": key, "secret_key": secret}
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


def image_type(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff") and data.endswith(b"\xff\xd9"):
        return "image/jpeg"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return None
