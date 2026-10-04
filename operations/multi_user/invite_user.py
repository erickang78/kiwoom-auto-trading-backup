"""Initialize an isolated tenant and issue its one-time activation invitation."""

import argparse
import os
from pathlib import Path

from tenant_auth import TenantAuth


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    if not args.root.is_dir() or args.root.is_symlink():
        parser.error("tenant root must be an existing directory")
    os.umask(0o077)
    auth = TenantAuth(args.root)
    auth.initialize()
    print("One-time activation code (expires in 24 hours; deliver privately):")
    print(auth.invite())


if __name__ == "__main__":
    main()
