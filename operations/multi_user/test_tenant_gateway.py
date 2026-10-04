import http.client
import threading
import tempfile
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from tenant_auth import TenantAuth


class TenantGatewayTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        secrets_dir = root / "secrets"
        secrets_dir.mkdir()
        (secrets_dir / "dashboard-token").write_text("existing-private-dashboard-key")
        page = root / "dashboard-source/dist"
        page.mkdir(parents=True)
        (page / "index.html").write_text("<html><script>const TOKEN = 'old';</script></body></html>")
        (page / "stock-list.js").write_text("const stocks=[];")
        backup = root / "backup-tools"
        backup.mkdir()
        (backup / "dashboard-status.js").write_text("window.backupStatus=true;")
        (backup / "backup_status.py").write_text("def read_status(): return {'ok': True}\n")
        auth = TenantAuth(root)
        auth.initialize()
        auth.bootstrap_existing_key(secrets_dir / "dashboard-token")
        source = Path(__file__).with_name("tenant_gateway.py").read_text().replace("/opt/kiwoom", str(root))
        namespace = {"__name__": "test_gateway"}
        exec(compile(source, "tenant_gateway.py", "exec"), namespace)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), namespace["Handler"])
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read().decode()
        finally:
            conn.close()

    def test_owner_login_keeps_page_and_blocks_unauthenticated_api(self):
        status, _, _ = self.request("GET", "/v1/account")
        self.assertEqual(status, 401)
        status, _, _ = self.request("GET", "/v1/backup/status")
        self.assertEqual(status, 401)
        status, _, page = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("비밀번호", page)
        status, headers, _ = self.request(
            "POST", "/login", "password=existing-private-dashboard-key",
            {"Origin": "https://example.invalid", "Content-Type": "application/x-www-form-urlencoded"},
        )
        self.assertEqual(status, 303)
        cookie = headers["Set-Cookie"].split(";", 1)[0]
        status, _, page = self.request("GET", "/", headers={"Cookie": cookie})
        self.assertEqual(status, 200)
        self.assertIn("window.backupStatus=true", page)
        self.assertNotIn("existing-private-dashboard-key", page)
        self.assertIn("const TOKEN = '';", page)
        status, _, body = self.request("GET", "/v1/backup/status", headers={"Cookie": cookie})
        self.assertEqual(status, 200)
        self.assertIn('"ok": true', body)


if __name__ == "__main__":
    unittest.main()
