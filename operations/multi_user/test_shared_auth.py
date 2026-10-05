import tempfile
import unittest
from pathlib import Path

from shared_admin import bootstrap_owner
from shared_auth import SharedAuth
from tenant_auth import TenantAuth


class SharedAuthTest(unittest.TestCase):
    def test_one_tenant_cannot_be_reserved_for_two_users(self):
        with tempfile.TemporaryDirectory() as directory:
            auth = SharedAuth(Path(directory) / "users.sqlite3")
            auth.initialize()
            auth.add_user("pilot", "pilot-001")
            with self.assertRaises(ValueError):
                auth.add_user("another", "pilot-001")

    def test_new_password_minimum_is_ten_characters(self):
        with tempfile.TemporaryDirectory() as directory:
            auth = SharedAuth(Path(directory) / "users.sqlite3")
            auth.initialize()
            auth.add_user("pilot", "pilot-001")
            invite = auth.invite("pilot")
            self.assertFalse(auth.activate("pilot", invite, "123456789"))
            self.assertTrue(auth.activate("pilot", invite, "1234567890"))
            session = auth.login("pilot", "1234567890")
            self.assertFalse(auth.change_password(session, "1234567890", "abcdefghi"))
            self.assertTrue(auth.change_password(session, "1234567890", "abcdefghij"))

    def test_bootstrap_owner_reuses_hash_without_copying_key(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tenant = TenantAuth(root / "owner")
            tenant.initialize()
            key = root / "owner/secrets/dashboard-token"
            key.write_text("private-existing-key")
            tenant.bootstrap_existing_key(key)
            shared = SharedAuth(root / "shared/secrets/users.sqlite3")
            shared.initialize()
            bootstrap_owner(shared, tenant.db_path)
            session = shared.login("owner", "private-existing-key")
            self.assertEqual(shared.session_user(session)["tenant_id"], "owner")
            shared.logout(session)
            self.assertIsNone(shared.session_user(session))
            self.assertNotIn("private-existing-key", shared.path.read_bytes().decode(errors="ignore"))


if __name__ == "__main__":
    unittest.main()
