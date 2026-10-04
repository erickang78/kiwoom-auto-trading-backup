import tempfile
import unittest
from pathlib import Path

from shared_admin import bootstrap_owner
from shared_auth import SharedAuth
from tenant_auth import TenantAuth


class SharedAuthTest(unittest.TestCase):
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
