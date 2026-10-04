import tempfile
import unittest
from pathlib import Path

from tenant_auth import TenantAuth


class TenantAuthTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.auth = TenantAuth(Path(self.temp.name))
        self.auth.initialize()

    def test_one_time_invite_password_and_session(self):
        token = self.auth.invite()
        self.assertFalse(self.auth.activate("wrong", "long-enough-password"))
        self.assertTrue(self.auth.activate(token, "long-enough-password"))
        self.assertFalse(self.auth.activate(token, "different-password"))
        self.assertFalse(self.auth.verify_password("wrong"))
        self.assertTrue(self.auth.verify_password("long-enough-password"))
        session = self.auth.new_session()
        self.assertTrue(self.auth.valid_session(session))
        self.assertFalse(self.auth.valid_session(session + "x"))
        with self.assertRaises(ValueError):
            self.auth.invite()

    def test_last_invitation_wins_and_weak_password_rejected(self):
        old = self.auth.invite()
        current = self.auth.invite()
        self.assertFalse(self.auth.activate(old, "long-enough-password"))
        self.assertFalse(self.auth.activate(current, "short"))
        self.assertTrue(self.auth.activate(current, "long-enough-password"))

    def test_tenants_do_not_share_credentials(self):
        other_root = Path(self.temp.name) / "other"
        other = TenantAuth(other_root)
        other.initialize()
        token = self.auth.invite()
        self.assertFalse(other.activate(token, "long-enough-password"))
        self.assertTrue(self.auth.activate(token, "long-enough-password"))
        self.assertFalse(other.valid_session(self.auth.new_session()))

    def test_existing_owner_key_migrates_without_changing_login_secret(self):
        key = Path(self.temp.name) / "secrets/dashboard-token"
        key.write_text("existing-private-dashboard-key\n")
        self.auth.bootstrap_existing_key(key)
        self.assertTrue(self.auth.verify_password("existing-private-dashboard-key"))
        self.assertFalse(self.auth.verify_password("different-key"))
        with self.assertRaises(ValueError):
            self.auth.bootstrap_existing_key(key)


if __name__ == "__main__":
    unittest.main()
