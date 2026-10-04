import tempfile
import unittest
from pathlib import Path

from preflight import inspect


ORIGIN = "https://pilot.example.test"


class TenantPreflightTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for folder in ("dashboard/dist", "root", "config"):
            (self.root / folder).mkdir(parents=True)
        (self.root / "dashboard/dist/index.html").write_text(
            f"<html><script>TOKEN=''</script><a href='{ORIGIN}'></a></html>"
        )
        (self.root / "root/dashboard_gateway.py").write_text(
            f"ORIGIN = '{ORIGIN}'\nKEY = Path('/opt/kiwoom/secrets/dashboard-token')\n"
        )
        (self.root / "config/Caddyfile").write_text(f"{ORIGIN} {{ reverse_proxy 127.0.0.1:8788 }}\n")

    def test_clean_candidate_passes(self):
        self.assertEqual(inspect(self.root, ORIGIN), [])

    def test_original_account_and_database_are_blocked(self):
        page = self.root / "dashboard/dist/index.html"
        page.write_text(page.read_text() + "0000-0000 ericgolf https://example.invalid")
        (self.root / "state.sqlite3").write_bytes(b"SQLite format 3\0")
        issues = inspect(self.root, ORIGIN)
        self.assertTrue(any("current account display" in issue for issue in issues))
        self.assertTrue(any("operator branding" in issue for issue in issues))
        self.assertTrue(any("private state" in issue for issue in issues))

    def test_existing_origin_is_blocked(self):
        self.assertTrue(any("existing operator" in issue for issue in inspect(self.root, "https://example.invalid")))


if __name__ == "__main__":
    unittest.main()
