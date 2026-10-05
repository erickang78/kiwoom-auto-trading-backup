import http.client
import struct
import zlib
import json
import re
import sqlite3
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlencode, parse_qs

from shared_auth import SharedAuth
from shared_gateway import SharedGateway
from tenant_auth import digest


class FakeBackend(BaseHTTPRequestHandler):
    marker = ""
    expected_token = ""
    token_path = None

    def log_message(self, *_):
        pass

    def do_GET(self):
        self.answer()

    def do_POST(self):
        self.answer()

    def answer(self):
        expected = self.token_path.read_text().strip() if self.token_path else self.expected_token
        if self.headers.get("Authorization") != "Bearer " + expected:
            self.send_error(401)
            return
        body = json.dumps({"marker": self.marker}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class SharedGatewayTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        tenants = {}
        for marker in ("owner", "pilot"):
            static = root / marker
            static.mkdir()
            (static / "index.html").write_text('<html><body><img class="ericgolf-logo" src="data:image/jpeg;base64,AAE="><script>const TOKEN=\'secret\';</script></body></html>')
            (static / "stock-list.js").write_text("const stocks=[]")
            token_file = root / (marker + ".token")
            token_file.write_text(marker + "-backend-key")
            handler = type(marker.title() + "Backend", (FakeBackend,), {"marker": marker, "expected_token": marker + "-backend-key", "token_path": token_file})
            backend = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            threading.Thread(target=backend.serve_forever, daemon=True).start()
            self.addCleanup(backend.server_close)
            self.addCleanup(backend.shutdown)
            tenant_id = "owner" if marker == "owner" else "pilot-001"
            credentials = root / (marker + "-secrets")
            credentials.mkdir()
            state = root / (marker + "-trading.sqlite3")
            with sqlite3.connect(state) as db:
                db.execute("CREATE TABLE portfolios (enabled INTEGER)")
                db.execute("CREATE TABLE intents (status TEXT)")
            tenants[tenant_id] = {"api_port": backend.server_port, "dashboard_root": str(static), "backend_token_file": str(token_file), "backend_origin": "https://backend.example.test", "real_credentials_file": str(credentials / "real.json"), "upbit_credentials_file": str(credentials / "upbit.json"), "auto_trading_state_file": str(state)}
        (root / "config.json").write_text(json.dumps({"origin": "https://shared.example.test", "port": 8898, "tenants": tenants}))
        self.auth = SharedAuth(root / "secrets/users.sqlite3")
        self.auth.initialize()
        salt = bytes.fromhex("00" * 16)
        self.auth.add_user("owner", "owner", salt.hex(), digest("owner-private-password", salt))
        self.auth.add_user("pilot", "pilot-001")
        invite = self.auth.invite("pilot")
        self.assertTrue(self.auth.activate("pilot", invite, "pilot-private-password"))
        self.assertFalse(self.auth.activate("pilot", invite, "pilot-private-password"))
        app = SharedGateway(root)
        self.app = app
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), app.handler())
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, method, path, data=None, headers=None, csrf=True):
        headers = dict(headers or {})
        headers.setdefault("Host", "shared.example.test")
        if csrf and method == "POST" and path in ("/login", "/activate", "/change-password", "/logout", "/account/credentials", "/account/api-key", "/account/kakao"):
            form_path = "/account" if path.startswith("/account/") else path if path != "/logout" else "/"
            _, form_headers, form = self.request("GET", form_path, headers=headers)
            token = re.search(r'name="_csrf" value="([A-Za-z0-9_-]{43})"', form).group(1)
            fields = parse_qs(data or "")
            fields["_csrf"] = [token]
            data = urlencode(fields, doseq=True)
            headers["Cookie"] = "; ".join(filter(None, [headers.get("Cookie", ""), form_headers["Set-Cookie"].split(";", 1)[0]]))
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        try:
            conn.request(method, path, body=data, headers=headers or {})
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read().decode(errors="replace")
        finally:
            conn.close()

    def login(self, username, password):
        status, headers, _ = self.request("POST", "/login", urlencode({"username": username, "password": password}), {"Origin": "https://shared.example.test", "Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(status, 303)
        return headers["Set-Cookie"].split(";", 1)[0]

    def test_each_session_routes_only_to_its_tenant(self):
        self.assertEqual(self.request("GET", "/v1/marker")[0], 401)
        owner_cookie = self.login("owner", "owner-private-password")
        pilot_cookie = self.login("pilot", "pilot-private-password")
        for cookie, marker in ((owner_cookie, "owner"), (pilot_cookie, "pilot")):
            status, _, body = self.request("GET", "/v1/marker?tenant_id=pilot-001", headers={"Cookie": cookie, "Authorization": "Bearer injected"})
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)["marker"], marker)
            status, _, page = self.request("GET", "/", headers={"Cookie": cookie})
            self.assertEqual(status, 200)
            self.assertIn("const TOKEN='';", page)
            self.assertNotIn(marker + "-backend-key", page)
        self.assertEqual(self.request("POST", "/v1/marker", "{}", {"Cookie": owner_cookie, "Origin": "https://evil.example.test"})[0], 403)
        self.assertEqual(self.request("POST", "/v1/marker", "{}", {"Cookie": owner_cookie, "Origin": "https://shared.example.test"})[0], 200)

    def test_logout_revokes_session(self):
        cookie = self.login("owner", "owner-private-password")
        self.assertEqual(self.request("POST", "/logout", headers={"Cookie": cookie, "Origin": "https://shared.example.test"})[0], 303)
        self.assertEqual(self.request("GET", "/v1/marker", headers={"Cookie": cookie})[0], 401)

    def test_auth_forms_accept_same_site_origin_fallback(self):
        for origin in ("https://shared.example.test", None, "null"):
            with self.subTest(origin=origin):
                headers = {"Host": "shared.example.test", "Referer": "https://shared.example.test/", "Content-Type": "application/x-www-form-urlencoded"}
                if origin is not None:
                    headers["Origin"] = origin
                status, response, _ = self.request("POST", "/login", urlencode({"username": "owner", "password": "owner-private-password"}), headers)
                self.assertEqual(status, 303)
                cookie = response["Set-Cookie"].split(";", 1)[0]
                self.assertEqual(self.request("GET", "/v1/marker", headers={"Cookie": cookie})[0], 200)
                self.assertEqual(self.request("POST", "/logout", headers={**headers, "Cookie": cookie})[0], 303)
                self.assertEqual(self.request("GET", "/v1/marker", headers={"Cookie": cookie})[0], 401)

    def test_auth_forms_reject_cross_site_and_invalid_csrf(self):
        data = urlencode({"username": "owner", "password": "owner-private-password"})
        for headers in ({"Origin": "https://evil.example.test"}, {"Origin": "null", "Host": "evil.example.test"}):
            self.assertEqual(self.request("POST", "/login", data, headers)[0], 403)
        for origin in (None, "null", "https://shared.example.test"):
            for cookie, token in (("", ""), ("a" * 43, "b" * 43), ("a" * 43, ""), ("", "a" * 43)):
                headers = {"Cookie": "__Host-moa_csrf=" + cookie}
                if origin is not None:
                    headers["Origin"] = origin
                with self.subTest(origin=origin, cookie_present=bool(cookie), token_present=bool(token)):
                    self.assertEqual(self.request("POST", "/login", data + "&_csrf=" + token, headers, csrf=False)[0], 403)

    def test_browser_form_without_origin_or_referer(self):
        status, headers, form = self.request("GET", "/login")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Referrer-Policy"], "no-referrer")
        self.assertIn("Secure; HttpOnly; SameSite=Strict", headers["Set-Cookie"])
        token = re.search(r'name="_csrf" value="([A-Za-z0-9_-]{43})"', form).group(1)
        data = urlencode({"username": "owner", "password": "owner-private-password", "_csrf": token})
        status, response, _ = self.request("POST", "/login", data, {"Cookie": headers["Set-Cookie"].split(";", 1)[0]}, csrf=False)
        self.assertEqual(status, 303)
        cookie = response["Set-Cookie"].split(";", 1)[0]
        self.assertEqual(self.request("GET", "/change-password", headers={"Cookie": cookie})[0], 200)
        self.assertEqual(self.request("POST", "/change-password", urlencode({"current_password": "owner-private-password", "new_password": "new-private-password", "confirm_password": "new-private-password"}), {"Cookie": cookie})[0], 303)
        self.assertIsNotNone(self.auth.login("owner", "new-private-password"))

    def test_api_posts_keep_strict_origin_requirement(self):
        cookie = self.login("owner", "owner-private-password")
        for origin in (None, "null"):
            with self.subTest(origin=origin):
                headers = {"Cookie": cookie, "Referer": "https://shared.example.test/", "Host": "shared.example.test"}
                if origin is not None:
                    headers["Origin"] = origin
                self.assertEqual(self.request("POST", "/v1/marker", "{}", headers)[0], 403)

    def test_password_change_requires_current_password_and_revokes_sessions(self):
        cookie = self.login("owner", "owner-private-password")
        other_cookie = self.login("owner", "owner-private-password")
        self.assertEqual(self.request("GET", "/change-password")[0], 401)
        fields = {"current_password": "owner-private-password", "new_password": "new-private-password", "confirm_password": "new-private-password"}
        self.assertEqual(self.request("POST", "/change-password", urlencode({**fields, "current_password": "wrong"}), {"Cookie": cookie, "Origin": "https://shared.example.test"})[0], 401)
        self.assertEqual(self.request("POST", "/change-password", urlencode({**fields, "confirm_password": "different"}), {"Cookie": cookie, "Origin": "https://shared.example.test"})[0], 400)
        self.assertEqual(self.request("POST", "/change-password", urlencode(fields), {"Cookie": cookie, "Origin": "https://evil.example.test"})[0], 403)
        self.assertEqual(self.request("POST", "/change-password", urlencode(fields), {"Cookie": cookie, "Origin": "https://shared.example.test"})[0], 303)
        self.assertEqual(self.request("GET", "/v1/marker", headers={"Cookie": cookie})[0], 401)
        self.assertEqual(self.request("GET", "/v1/marker", headers={"Cookie": other_cookie})[0], 401)
        self.assertIsNone(self.auth.login("owner", "owner-private-password"))
        self.assertIsNotNone(self.auth.login("owner", "new-private-password"))

    def test_account_settings_keep_tenant_credentials_private(self):
        owner = self.login("owner", "owner-private-password")
        pilot = self.login("pilot", "pilot-private-password")
        self.assertEqual(self.request("GET", "/account")[0], 401)
        page = self.request("GET", "/account", headers={"Cookie": owner})[2]
        self.assertIn("회원정보 수정", page)
        self.assertNotIn("owner-backend-key", page)
        for cookie, kind, password in ((owner, "kiwoom-real", "owner-private-password"), (pilot, "upbit", "pilot-private-password")):
            fields = urlencode({"kind": kind, "key": "new-access-key", "secret": "new-secret-key", "password": password})
            self.assertEqual(self.request("POST", "/account/credentials", fields, {"Cookie": cookie})[0], 303)
        owner_real = Path(self.app.tenants["owner"]["real_credentials_file"])
        pilot_upbit = Path(self.app.tenants["pilot-001"]["upbit_credentials_file"])
        self.assertEqual(json.loads(owner_real.read_text()), {"app_key": "new-access-key", "app_secret": "new-secret-key"})
        self.assertEqual(json.loads(pilot_upbit.read_text()), {"access_key": "new-access-key", "secret_key": "new-secret-key"})
        self.assertEqual(owner_real.stat().st_mode & 0o777, 0o600)
        self.assertNotIn("new-secret-key", self.request("GET", "/account", headers={"Cookie": owner})[2])
        self.assertNotIn("new-secret-key", self.request("GET", "/account", headers={"Cookie": pilot})[2])

    def test_account_credentials_require_password_and_csrf(self):
        cookie = self.login("owner", "owner-private-password")
        fields = urlencode({"kind": "kiwoom-real", "key": "new-access-key", "secret": "new-secret-key", "password": "wrong"})
        self.assertNotEqual(self.request("POST", "/account/credentials", fields, {"Cookie": cookie})[0], 303)
        self.assertEqual(self.request("POST", "/account/credentials", fields, {"Cookie": cookie}, csrf=False)[0], 403)
        self.assertFalse(Path(self.app.tenants["owner"]["real_credentials_file"]).exists())

    def test_kiwoom_credentials_are_locked_while_trading_runs(self):
        cookie = self.login("owner", "owner-private-password")
        state = self.app.tenants["owner"]["auto_trading_state_file"]
        with sqlite3.connect(state) as db:
            db.execute("INSERT INTO portfolios VALUES (1)")
        fields = urlencode({"kind": "kiwoom-real", "key": "new-access-key", "secret": "new-secret-key", "password": "owner-private-password"})
        self.assertNotEqual(self.request("POST", "/account/credentials", fields, {"Cookie": cookie})[0], 303)
        self.assertFalse(Path(self.app.tenants["owner"]["real_credentials_file"]).exists())

    def test_account_hides_username_change_and_shows_current_photo_and_password_form(self):
        cookie = self.login("owner", "owner-private-password")
        page = self.request("GET", "/account", headers={"Cookie": cookie})[2]
        self.assertIn('src="data:image/jpeg;base64,AAE="', page)
        self.assertIn('width:52px;height:52px', page)
        self.assertNotIn('action="/account/username"', page)
        self.assertIn('name="confirm_password"', page)
        self.assertIn('minlength="10"', page)
        fields = urlencode({"new_username": "sugjin", "password": "owner-private-password"})
        self.assertEqual(self.request("POST", "/account/username", fields, {"Cookie": cookie})[0], 404)

    def test_kakao_account_route_is_scoped_and_requires_reauthentication(self):
        self.assertEqual(self.request("GET", "/account/kakao/status")[0], 401)
        cookie = self.login("owner", "owner-private-password")
        status, _, body = self.request("GET", "/account/kakao/status", headers={"Cookie": cookie})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["marker"], "owner")
        for action in ("setup", "disconnect"):
            fields = urlencode({"action": action, "password": "wrong", "client_id": "fake"})
            self.assertEqual(self.request("POST", "/account/kakao", fields, {"Cookie": cookie})[0], 401)
            fields = urlencode({"action": action, "password": "owner-private-password", "client_id": "fake"})
            self.assertEqual(self.request("POST", "/account/kakao", fields, {"Cookie": cookie}, csrf=False)[0], 403)
            self.assertEqual(self.request("POST", "/account/kakao", fields, {"Cookie": cookie})[0], 200)
        self.assertEqual(self.request("POST", "/account/kakao", urlencode({"action": "test"}), {"Cookie": cookie})[0], 400)

    def test_api_key_rotation_is_session_protected_and_tenant_scoped(self):
        owner = self.login("owner", "owner-private-password")
        pilot = self.login("pilot", "pilot-private-password")
        owner_token = Path(self.app.tenants["owner"]["backend_token_file"])
        pilot_token = Path(self.app.tenants["pilot-001"]["backend_token_file"])
        fields = urlencode({"new_key": "a-new-long-private-api-key-123", "password": "wrong"})
        self.assertNotEqual(self.request("POST", "/account/api-key", fields, {"Cookie": owner})[0], 303)
        self.assertEqual(self.request("POST", "/account/api-key", fields, {"Cookie": owner}, csrf=False)[0], 403)
        self.assertEqual(owner_token.read_text(), "owner-backend-key")
        fields = urlencode({"new_key": "a-new-long-private-api-key-123", "password": "owner-private-password"})
        self.assertEqual(self.request("POST", "/account/api-key", fields, {"Cookie": owner})[0], 303)
        self.assertEqual(owner_token.read_text().strip(), "a-new-long-private-api-key-123")
        self.assertEqual(owner_token.stat().st_mode & 0o777, 0o600)
        self.assertEqual(pilot_token.read_text(), "pilot-backend-key")
        for cookie, marker in ((owner, "owner"), (pilot, "pilot")):
            status, _, body = self.request("GET", "/v1/marker", headers={"Cookie": cookie})
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)["marker"], marker)
        for invalid in ("x" * 23, "x" * 257, "a" * 24 + " ", "x" * 24 + "\n", "é" * 24):
            fields = urlencode({"new_key": invalid, "password": "owner-private-password"})
            self.assertNotEqual(self.request("POST", "/account/api-key", fields, {"Cookie": owner})[0], 303)
        self.assertEqual(owner_token.read_text().strip(), "a-new-long-private-api-key-123")
        self.assertNotIn("a-new-long-private-api-key-123", self.request("GET", "/account", headers={"Cookie": owner})[2])
        self.assertEqual(self.request("GET", "/account", headers={"Cookie": pilot})[0], 200)

    def test_credential_config_rejects_protected_or_shared_paths(self):
        config = self.app.config
        root = self.app.root
        for path in (config["tenants"]["owner"]["backend_token_file"], config["tenants"]["pilot-001"]["upbit_credentials_file"]):
            with self.subTest(path=path):
                changed = json.loads(json.dumps(config))
                changed["tenants"]["owner"]["real_credentials_file"] = path
                (root / "config.json").write_text(json.dumps(changed))
                with self.assertRaises(ValueError):
                    SharedGateway(root)

    def test_tenant_token_files_cannot_overlap(self):
        changed = json.loads(json.dumps(self.app.config))
        changed["tenants"]["pilot-001"]["backend_token_file"] = changed["tenants"]["owner"]["backend_token_file"]
        (self.app.root / "config.json").write_text(json.dumps(changed))
        with self.assertRaises(ValueError):
            SharedGateway(self.app.root)

    def test_profile_photo_is_tenant_scoped_and_validated(self):
        owner = self.login("owner", "owner-private-password")
        pilot = self.login("pilot", "pilot-private-password")
        _, headers, page = self.request("GET", "/account", headers={"Cookie": owner})
        csrf = re.search(r'name="_csrf" value="([A-Za-z0-9_-]{43})"', page).group(1)
        cookies = owner + "; " + headers["Set-Cookie"].split(";", 1)[0]
        def chunk(kind, data):
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
        image = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(b"\0\0\0\0")) + chunk(b"IEND", b"")
        common = {"Cookie": cookies, "X-Moa-CSRF": csrf, "Content-Type": "image/png"}
        self.assertEqual(self.request("POST", "/account/photo", image, common, csrf=False)[0], 204)
        self.assertEqual(self.request("GET", "/account/photo", headers={"Cookie": owner})[0], 200)
        self.assertEqual(self.request("POST", "/account/photo", image, {**common, "Content-Type": "image/jpeg"}, csrf=False)[0], 400)
        self.assertEqual(self.request("POST", "/account/photo", image * 4000, common, csrf=False)[0], 400)
        self.assertEqual(self.request("GET", "/account/photo", headers={"Cookie": pilot})[0], 404)
        self.assertEqual(self.request("POST", "/account/photo", b"not-an-image", common, csrf=False)[0], 400)
        self.assertEqual(self.request("POST", "/account/photo", image, {**common, "X-Moa-CSRF": "wrong"}, csrf=False)[0], 403)
        self.assertEqual(self.request("GET", "/account/photo")[0], 401)


if __name__ == "__main__":
    unittest.main()
