"""One account per isolated tenant gateway; no public sign-up endpoint."""

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from pathlib import Path


def digest(value: str, salt: bytes) -> str:
    return hashlib.scrypt(value.encode(), salt=salt, n=16384, r=8, p=1).hex()


class TenantAuth:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.db_path = self.root / "secrets" / "tenant-auth.sqlite3"
        self.signing_key_path = self.root / "secrets" / "session-signing-key"

    def connect(self):
        db = sqlite3.connect(self.db_path, timeout=10)
        db.execute("PRAGMA busy_timeout=10000")
        return db

    def initialize(self):
        secrets_dir = self.root / "secrets"
        secrets_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(secrets_dir, 0o700)
        if not self.signing_key_path.exists():
            fd = os.open(self.signing_key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as file:
                file.write(secrets.token_hex(32))
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS account (id INTEGER PRIMARY KEY CHECK (id=1), salt TEXT, password_hash TEXT, session_epoch INTEGER NOT NULL DEFAULT 0)")
            db.execute("CREATE TABLE IF NOT EXISTS invitation (id INTEGER PRIMARY KEY CHECK (id=1), token_hash TEXT NOT NULL, expires_at INTEGER NOT NULL)")
            db.execute("INSERT OR IGNORE INTO account(id) VALUES (1)")
        os.chmod(self.db_path, 0o600)

    def invite(self, lifetime_seconds=86400):
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT password_hash FROM account WHERE id=1").fetchone()[0]:
                raise ValueError("account already activated")
            db.execute("INSERT OR REPLACE INTO invitation(id,token_hash,expires_at) VALUES(1,?,?)", (token_hash, int(time.time()) + lifetime_seconds))
        return token

    def bootstrap_existing_key(self, key_path: Path):
        """Migrate the owner's existing login key without printing or copying it."""
        password = Path(key_path).read_text().strip()
        if not password or len(password) > 1024:
            raise ValueError("existing login key is empty or too long")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT password_hash FROM account WHERE id=1").fetchone()
            if not row or row[0]:
                raise ValueError("account already activated")
            salt = secrets.token_bytes(16)
            db.execute("UPDATE account SET salt=?,password_hash=?,session_epoch=session_epoch+1 WHERE id=1", (salt.hex(), digest(password, salt)))
            db.execute("DELETE FROM invitation WHERE id=1")

    def activate(self, token: str, password: str):
        if len(password) < 12 or len(password) > 1024:
            return False
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            account = db.execute("SELECT password_hash FROM account WHERE id=1").fetchone()
            row = db.execute("SELECT token_hash,expires_at FROM invitation WHERE id=1").fetchone()
            if not account or account[0] or not row or row[1] < time.time() or not hmac.compare_digest(token_hash, row[0]):
                return False
            salt = secrets.token_bytes(16)
            db.execute("UPDATE account SET salt=?,password_hash=?,session_epoch=session_epoch+1 WHERE id=1", (salt.hex(), digest(password, salt)))
            db.execute("DELETE FROM invitation WHERE id=1")
        return True

    def verify_password(self, password: str):
        with self.connect() as db:
            row = db.execute("SELECT salt,password_hash FROM account WHERE id=1").fetchone()
        if not row or not row[1] or len(password) > 1024:
            return False
        return hmac.compare_digest(digest(password, bytes.fromhex(row[0])), row[1])

    def _key(self):
        return bytes.fromhex(self.signing_key_path.read_text().strip())

    def new_session(self):
        with self.connect() as db:
            epoch = db.execute("SELECT session_epoch FROM account WHERE id=1").fetchone()[0]
        payload = json.dumps([int(time.time()), epoch, secrets.token_hex(16)], separators=(",", ":")).encode()
        import base64
        value = base64.urlsafe_b64encode(payload).decode().rstrip("=")
        sig = hmac.new(self._key(), value.encode(), hashlib.sha256).hexdigest()
        return value + "." + sig

    def valid_session(self, cookie: str, ttl=7 * 86400):
        try:
            value, sig = cookie.rsplit(".", 1)
            if not hmac.compare_digest(sig, hmac.new(self._key(), value.encode(), hashlib.sha256).hexdigest()):
                return False
            import base64
            issued, epoch, _ = json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
            with self.connect() as db:
                current = db.execute("SELECT session_epoch FROM account WHERE id=1").fetchone()[0]
            return epoch == current and 0 <= time.time() - issued < ttl
        except (ValueError, KeyError, TypeError, sqlite3.Error):
            return False
