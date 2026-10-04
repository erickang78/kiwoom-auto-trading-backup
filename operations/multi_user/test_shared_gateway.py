import http.client
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlencode

from shared_auth import SharedAuth
from shared_gateway import SharedGateway
from tenant_auth import digest


class FakeBackend(BaseHTTPRequestHandler):
    marker = ""
    expected_token = ""

    def log_message(self, *_):
        pass

    def do_GET(self):
        self.answer()

    def do_POST(self):
        self.answer()

    def answer(self):
        if self.headers.get("Authorization") != "Bearer " + self.expected_token:
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
            (static / "index.html").write_text("<html><body><script>const TOKEN='secret';</script></body></html>")
            (static / "stock-list.js").write_text("const stocks=[]")
            token_file = root / (marker + ".token")
            token_file.write_text(marker + "-backend-key")
            handler = type(marker.title() + "Backend", (FakeBackend,), {"marker": marker, "expected_token": marker + "-backend-key"})
            backend = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            threading.Thread(target=backend.serve_forever, daemon=True).start()
            self.addCleanup(backend.server_close)
            self.addCleanup(backend.shutdown)
            tenant_id = "owner" if marker == "owner" else "pilot-001"
            tenants[tenant_id] = {"api_port": backend.server_port, "dashboard_root": str(static), "backend_token_file": str(token_file), "backend_origin": "https://backend.example.test"}
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
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), app.handler())
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, method, path, data=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        try:
            conn.request(method, path, body=data, headers=headers or {})
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read().decode()
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


if __name__ == "__main__":
    unittest.main()
