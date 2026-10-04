"""Reject a candidate tenant bundle that still points at the original account.

This is a deployment gate, not a PII scanner or a full security audit.
It reads files only and never prints credential contents.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import urlparse


CURRENT_ORIGIN = "https://example.invalid"
FILES = {
    "dashboard": Path("dashboard/dist/index.html"),
    "gateway": Path("root/dashboard_gateway.py"),
    "caddy": Path("config/Caddyfile"),
}
PRIVATE_NAMES = {
    "dashboard-token",
    "session-signing-key",
    "tenant-auth.sqlite3",
    "real-credentials.json",
    "mock-credentials.json",
    "gold-credentials.json",
    "upbit-credentials.json",
}


def inspect(root: Path, origin: str) -> list[str]:
    issues: list[str] = []
    parsed = urlparse(origin)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.port
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        issues.append("origin must be a bare HTTPS origin")
    if origin.rstrip("/") == CURRENT_ORIGIN:
        issues.append("origin is the existing operator's dashboard")

    for label, relative in FILES.items():
        path = root / relative
        if not path.is_file():
            issues.append(f"missing {label}: {relative}")
            continue
        content = path.read_text(errors="replace")
        if re.search(r"(?<![A-Za-z0-9.-])203-0-113-10\.sslip\.io", content):
            issues.append(f"{label} still references the current operator's URL")
        required_origin = parsed.hostname if label == "caddy" else origin
        if label != "dashboard" and required_origin not in content:
            issues.append(f"{label} does not reference the new HTTPS origin")
        if label == "dashboard":
            if "5190-" in content:
                issues.append("dashboard still contains the current account display")
            if "ericgolf" in content.lower() or "erickang" in content.lower():
                issues.append("dashboard still contains current operator branding")
        if label == "gateway" and "dashboard-token" not in content:
            issues.append("gateway does not load a private dashboard token")
        if label == "gateway" and re.search(r"/opt/kiwoom(?=/|['\"])", content):
            issues.append("gateway still references the operator's data root")

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        name = path.name.lower()
        if name in PRIVATE_NAMES or name.endswith((".sqlite3", ".sqlite", ".db")):
            issues.append(f"candidate bundle contains private state: {path.relative_to(root)}")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="candidate tenant bundle root")
    parser.add_argument("--origin", required=True, help="new tenant HTTPS origin")
    args = parser.parse_args()
    if not args.root.is_dir():
        parser.error("candidate root must be a directory")
    issues = inspect(args.root, args.origin)
    if issues:
        print(f"Tenant preflight blocked ({len(issues)} issue(s)):")
        for issue in issues:
            print(f"- {issue}")
        return 1
    print("Tenant preflight passed: no known original-account markers or private state")
    return 0


if __name__ == "__main__":
    sys.exit(main())
