"""One-time migration from the existing dashboard key to password login."""

import argparse
import os
from pathlib import Path

from tenant_auth import TenantAuth


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    auth = TenantAuth(args.root)
    auth.initialize()
    auth.bootstrap_existing_key(args.root / "secrets/dashboard-token")
    print("Owner login migrated; the existing access key is now accepted as the password")


if __name__ == "__main__":
    main()
