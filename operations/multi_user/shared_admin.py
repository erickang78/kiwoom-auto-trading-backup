"""Private operator commands for the shared login database."""

import argparse
import sqlite3
from pathlib import Path

from shared_auth import SharedAuth


def bootstrap_owner(auth: SharedAuth, source: Path):
    with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as db:
        row = db.execute("SELECT salt,password_hash FROM account WHERE id=1").fetchone()
    if not row or not row[0] or not row[1]:
        raise ValueError("existing owner login is not activated")
    auth.add_user("owner", "owner", row[0], row[1])
    print("Owner account prepared with existing password hash; username: owner")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    sub = parser.add_subparsers(dest="action", required=True)
    owner = sub.add_parser("bootstrap-owner")
    owner.add_argument("--source", type=Path, required=True)
    add = sub.add_parser("add-user")
    add.add_argument("--username", required=True)
    add.add_argument("--tenant-id", required=True)
    invite = sub.add_parser("invite")
    invite.add_argument("--username", required=True)
    args = parser.parse_args()
    auth = SharedAuth(args.root / "secrets/users.sqlite3")
    auth.initialize()
    if args.action == "bootstrap-owner":
        bootstrap_owner(auth, args.source)
    elif args.action == "add-user":
        auth.add_user(args.username, args.tenant_id)
        print("Disabled invited user record prepared")
    else:
        print("One-time invitation code (deliver privately; expires in 24 hours):")
        print(auth.invite(args.username))


if __name__ == "__main__":
    main()
