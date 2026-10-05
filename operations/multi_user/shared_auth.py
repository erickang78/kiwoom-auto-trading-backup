"""Central login store mapping each invited account to one fixed tenant ID."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import time
from pathlib import Path

from tenant_auth import digest


class SharedAuth:
    def __init__(self, path: Path):
        self.path = Path(path)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=10000")
        return db

    def initialize(self):
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.path.parent, 0o700)
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, salt TEXT, password_hash TEXT, enabled INTEGER NOT NULL DEFAULT 0)")
            db.execute("CREATE TABLE IF NOT EXISTS invitations (username TEXT PRIMARY KEY REFERENCES users(username), token_hash TEXT NOT NULL, expires_at INTEGER NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, username TEXT NOT NULL REFERENCES users(username), expires_at INTEGER NOT NULL)")
            db.execute("CREATE INDEX IF NOT EXISTS sessions_expiry ON sessions(expires_at)")
        os.chmod(self.path, 0o600)

    def add_user(self, username: str, tenant_id: str, salt: str | None = None, password_hash: str | None = None):
        if not re.fullmatch(r"[a-z][a-z0-9-]{2,30}", username):
            raise ValueError("invalid username")
        if not re.fullmatch(r"[a-z][a-z0-9-]{2,30}", tenant_id):
            raise ValueError("invalid tenant ID")
        with self.connect() as db:
            db.execute("INSERT INTO users(username,tenant_id,salt,password_hash,enabled) VALUES(?,?,?,?,?)", (username, tenant_id, salt, password_hash, int(bool(password_hash))))

    def invite(self, username: str, lifetime_seconds=86400):
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT enabled FROM users WHERE username=?", (username,)).fetchone()
            if not row or row[0]:
                raise ValueError("user missing or already active")
            db.execute("INSERT OR REPLACE INTO invitations(username,token_hash,expires_at) VALUES(?,?,?)", (username, token_hash, int(time.time()) + lifetime_seconds))
        return token

    def activate(self, username: str, token: str, password: str):
        if not 10 <= len(password) <= 1024:
            return False
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT u.enabled,i.token_hash,i.expires_at FROM users u LEFT JOIN invitations i USING(username) WHERE u.username=?", (username,)).fetchone()
            if not row or row[0] or not row[1] or row[2] < time.time() or not hmac.compare_digest(token_hash, row[1]):
                return False
            salt = secrets.token_bytes(16)
            db.execute("UPDATE users SET salt=?,password_hash=?,enabled=1 WHERE username=?", (salt.hex(), digest(password, salt), username))
            db.execute("DELETE FROM invitations WHERE username=?", (username,))
        return True

    def login(self, username: str, password: str, ttl=7 * 86400):
        if len(password) > 1024:
            return None
        with self.connect() as db:
            row = db.execute("SELECT salt,password_hash,enabled FROM users WHERE username=?", (username,)).fetchone()
            if not row or not row[2] or not row[1] or not hmac.compare_digest(digest(password, bytes.fromhex(row[0])), row[1]):
                return None
            token = secrets.token_urlsafe(32)
            db.execute("DELETE FROM sessions WHERE expires_at<?", (int(time.time()),))
            db.execute("INSERT INTO sessions(token_hash,username,expires_at) VALUES(?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), username, int(time.time()) + ttl))
            return token

    def session_user(self, token: str):
        if not token or len(token) > 128:
            return None
        with self.connect() as db:
            row = db.execute("SELECT u.username,u.tenant_id FROM sessions s JOIN users u ON u.username=s.username WHERE s.token_hash=? AND s.expires_at>? AND u.enabled=1", (hashlib.sha256(token.encode()).hexdigest(), int(time.time()))).fetchone()
            return dict(row) if row else None

    def logout(self, token: str):
        if token and len(token) <= 128:
            with self.connect() as db:
                db.execute("DELETE FROM sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))

    def verify_session_password(self, token: str, password: str):
        if not token or len(token) > 128 or len(password) > 1024:
            return False
        with self.connect() as db:
            row = db.execute("SELECT u.salt,u.password_hash FROM sessions s JOIN users u ON u.username=s.username WHERE s.token_hash=? AND s.expires_at>? AND u.enabled=1", (hashlib.sha256(token.encode()).hexdigest(), int(time.time()))).fetchone()
            return bool(row and row[0] and row[1] and hmac.compare_digest(digest(password, bytes.fromhex(row[0])), row[1]))

    def change_username(self, token: str, password: str, new_username: str):
        if not token or len(token) > 128 or len(password) > 1024 or not re.fullmatch(r"[a-z][a-z0-9-]{2,30}", new_username):
            return False
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT u.username,u.salt,u.password_hash FROM sessions s JOIN users u ON u.username=s.username WHERE s.token_hash=? AND s.expires_at>? AND u.enabled=1", (hashlib.sha256(token.encode()).hexdigest(), int(time.time()))).fetchone()
            if not row or not hmac.compare_digest(digest(password, bytes.fromhex(row[1])), row[2]) or db.execute("SELECT 1 FROM users WHERE username=?", (new_username,)).fetchone():
                return False
            db.execute("DELETE FROM sessions WHERE username=?", (row[0],))
            db.execute("DELETE FROM invitations WHERE username=?", (row[0],))
            db.execute("UPDATE users SET username=? WHERE username=?", (new_username, row[0]))
        return True

    def change_password(self, token: str, current_password: str, new_password: str):
        if not token or len(token) > 128 or not 10 <= len(new_password) <= 1024 or len(current_password) > 1024:
            return False
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT u.username,u.salt,u.password_hash FROM sessions s JOIN users u ON u.username=s.username WHERE s.token_hash=? AND s.expires_at>? AND u.enabled=1", (hashlib.sha256(token.encode()).hexdigest(), int(time.time()))).fetchone()
            if not row or not hmac.compare_digest(digest(current_password, bytes.fromhex(row[1])), row[2]):
                return False
            salt = secrets.token_bytes(16)
            db.execute("UPDATE users SET salt=?,password_hash=? WHERE username=?", (salt.hex(), digest(new_password, salt), row[0]))
            db.execute("DELETE FROM sessions WHERE username=?", (row[0],))
        return True
