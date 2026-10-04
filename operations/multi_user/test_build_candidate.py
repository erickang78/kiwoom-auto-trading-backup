import tempfile
import unittest
from pathlib import Path

from build_candidate import build
from preflight import inspect


SOURCE = Path(__file__).resolve().parents[2] / "server-baseline"
ORIGIN = "https://pilot-001.example.invalid"


class PilotBundleTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / "pilot"

    def test_bundle_is_isolated_and_contains_no_operator_artifacts(self):
        build(SOURCE, self.output, "pilot-001", ORIGIN, 8887, 8888)
        self.assertEqual(inspect(self.output, ORIGIN), [])
        page = (self.output / "dashboard/dist/index.html").read_text()
        self.assertNotIn("data:image/jpeg;base64,", page)
        self.assertNotIn("5190-", page)
        self.assertNotIn("erickang", page)
        gateway = (self.output / "root/dashboard_gateway.py").read_text()
        self.assertIn("/opt/kiwoom-tenants/pilot-001/secrets/dashboard-token", gateway)
        self.assertIn("'127.0.0.1',8888", gateway)
        for unit in (self.output / "config/systemd").glob("*.service"):
            self.assertIn("User=kiwoom-pilot-001", unit.read_text(), unit.name)
        self.assertFalse(any(path.name.endswith((".db", ".sqlite3")) for path in self.output.rglob("*")))

    def test_refuses_production_ports_and_existing_output(self):
        with self.assertRaises(ValueError):
            build(SOURCE, self.output, "pilot-001", ORIGIN, 8787, 8888)
        build(SOURCE, self.output, "pilot-001", ORIGIN, 8887, 8888)
        with self.assertRaises(FileExistsError):
            build(SOURCE, self.output, "pilot-001", ORIGIN, 8887, 8888)


if __name__ == "__main__":
    unittest.main()
