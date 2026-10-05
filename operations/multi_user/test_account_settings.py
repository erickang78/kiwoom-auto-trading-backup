import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from account_settings import image_type, save_credentials, stopped_trading, trading_stopped


class AccountSettingsTest(unittest.TestCase):
    def test_credentials_preserve_metadata_and_reject_symlinks_and_unknown_kind(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "real.json"
            path.write_text(json.dumps({"app_key": "old", "app_secret": "old", "metadata": "preserve"}))
            save_credentials(path, "kiwoom-real", "new", "replacement")
            self.assertEqual(json.loads(path.read_text())["metadata"], "preserve")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(ValueError):
                save_credentials(path, "kiwoom-real", "  ", "  ")
            alias = Path(directory) / "alias.json"
            alias.symlink_to(path)
            with self.assertRaises(ValueError):
                save_credentials(alias, "kiwoom-real", "x", "y")
            with self.assertRaises(ValueError):
                save_credentials(path, "unknown", "x", "y")

    def test_trading_guard_blocks_concurrent_enabling_and_unresolved_orders(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.sqlite3"
            with sqlite3.connect(path) as db:
                db.executescript("CREATE TABLE portfolios(enabled INTEGER); CREATE TABLE intents(status TEXT); INSERT INTO portfolios VALUES(0);")
            self.assertTrue(trading_stopped(str(path)))
            with stopped_trading(str(path)) as stopped:
                self.assertTrue(stopped)
                with sqlite3.connect(path, timeout=0) as competitor:
                    with self.assertRaises(sqlite3.OperationalError):
                        competitor.execute("UPDATE portfolios SET enabled=1")
            for status in ("accepted", "partial", "unknown", "reconcile_error"):
                with sqlite3.connect(path) as db:
                    db.execute("DELETE FROM intents")
                    db.execute("INSERT INTO intents VALUES(?)", (status,))
                with stopped_trading(str(path)) as stopped:
                    self.assertFalse(stopped)

    def test_image_headers_alone_truncated_and_oversized_files_are_rejected(self):
        for data in (b"\x89PNG\r\n\x1a\ninvalid", b"\xff\xd8\xffinvalid\xff\xd9", b"RIFFxxxxWEBPinvalid", b"x" * 262145):
            self.assertIsNone(image_type(data))


if __name__ == "__main__":
    unittest.main()
