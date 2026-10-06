import tempfile
import unittest
from pathlib import Path

from build_candidate import build, generic_dashboard
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
        self.assertIn("TenantAuth(Path('/opt/kiwoom-tenants/pilot-001'))", gateway)
        self.assertNotIn("TenantAuth(Path('/opt/kiwoom'))", gateway)
        self.assertIn("'127.0.0.1',8888", gateway)
        self.assertIn("TenantAuth", gateway)
        self.assertIn("if not authenticated and not public_health: return self.respond(401", gateway)
        self.assertIn("self.respond(403, {'error': 'pilot_read_only'})", gateway)
        self.assertNotIn("/opt/kiwoom'", gateway)
        self.assertTrue((self.output / "root/tenant_auth.py").is_file())
        self.assertTrue((self.output / "root/invite_user.py").is_file())
        for unit in (self.output / "config/systemd").glob("*.service"):
            self.assertIn("User=kiwoom-pilot-001", unit.read_text(), unit.name)
            self.assertIn("UMask=0077", unit.read_text(), unit.name)
        refresh_unit = (self.output / "config/systemd/kiwoom-refresh@pilot-001.service").read_text()
        self.assertIn("ExecStart=/usr/bin/python3", refresh_unit)
        self.assertIn("WorkingDirectory=/opt/kiwoom-tenants/pilot-001/current", refresh_unit)
        self.assertIn("Environment=PYTHONPATH=/opt/kiwoom-tenants/pilot-001/current", refresh_unit)
        self.assertIn("MemoryMax=128M", refresh_unit)
        self.assertIn("CPUQuota=20%", refresh_unit)
        self.assertIn("ReadWritePaths=/opt/kiwoom-tenants/pilot-001/state", refresh_unit)
        dashboard_unit = (self.output / "config/systemd/moa-dashboard@pilot-001.service").read_text()
        self.assertIn("WorkingDirectory=/opt/kiwoom-tenants/pilot-001", dashboard_unit)
        self.assertNotIn("/opt/kiwoom ", dashboard_unit)
        api = (self.output / "current/refresh_api.py").read_text()
        self.assertIn("if mode or is_flow or is_coin or is_trade or is_kakao", api)
        self.assertIn("is_auto_trading and body.get('action', 'status') not in ('status', 'performance')", api)
        self.assertIn("is_trading_control and body.get('action', 'status') != 'status'", api)
        self.assertIn("is_signal_validation and body.get('action', 'status') != 'status'", api)
        self.assertFalse(any(path.name.endswith((".db", ".sqlite3")) for path in self.output.rglob("*")))

    def test_dashboard_without_optional_creator_credit(self):
        page = (SOURCE / "dashboard/dist/index.html").read_text()
        import re
        page = re.sub(r'<div class="creator-credit"[^>]*>.*?</div>', "", page, flags=re.S)
        self.assertNotIn("erickang", generic_dashboard(page))

    def test_new_strategy_actions_remain_blocked_in_pilot(self):
        import ast, io, json, secrets
        from types import SimpleNamespace
        build(SOURCE, self.output, "pilot-001", ORIGIN, 8887, 8888)
        api=ast.parse((self.output / 'current/refresh_api.py').read_text())
        handler=next(n for n in api.body if isinstance(n,ast.ClassDef) and n.name=='Handler')
        method=next(n for n in handler.body if isinstance(n,ast.FunctionDef) and n.name=='do_POST')
        namespace={'TOKEN_PATH':SimpleNamespace(read_text=lambda:'synthetic-test-token'),
                   'ALLOWED_ORIGINS':{ORIGIN},'json':json,'secrets':secrets}
        exec(compile(ast.Module(body=[method],type_ignores=[]),'candidate-handler','exec'),namespace)
        for path,action in [('/v1/trading/auto',a) for a in ('allocate','start','stop','check_restart')]+[('/v1/trading/control',a) for a in ('pause','resume')]+[('/v1/trade/submit','submit'),('/v1/real/refresh','refresh')]:
            with self.subTest(path=path,action=action):
                body=json.dumps({'action':action,'market':'KR','strategy':'breakout','budget':'100000','confirmed':True}).encode()
                request=SimpleNamespace(path=path,headers={'Origin':ORIGIN,'Authorization':'Bearer synthetic-test-token','Content-Length':str(len(body))},rfile=io.BytesIO(body),_json=lambda status,body:(status,body))
                self.assertEqual(namespace['do_POST'](request),(403,{'error':'pilot_read_only'}))
        for name in ('auto_trading.py','strategy_budget.py'):
            text=(self.output/'current'/name).read_text()
            self.assertNotIn('/opt/kiwoom/',text)
        self.assertIn('/opt/kiwoom-tenants/pilot-001/state/auto-trading.sqlite3',(self.output/'current/auto_trading.py').read_text())

    def test_refuses_production_ports_and_existing_output(self):
        with self.assertRaises(ValueError):
            build(SOURCE, self.output, "pilot-001", ORIGIN, 8787, 8888)
        build(SOURCE, self.output, "pilot-001", ORIGIN, 8887, 8888)
        with self.assertRaises(FileExistsError):
            build(SOURCE, self.output, "pilot-001", ORIGIN, 8887, 8888)


if __name__ == "__main__":
    unittest.main()
