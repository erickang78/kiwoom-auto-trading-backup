"""Build a non-secret, isolated pilot bundle without touching production.

Generated files are candidates for review, not an installer. No service is
enabled and no broker credential or database is copied from the source.
"""

from __future__ import annotations

import argparse
import ast
import re
import shutil
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from preflight import inspect


SOURCE_ORIGIN = "https://example.invalid"
OLD_ORIGIN = "https://moa-invest-sep22.erickang78.chatgpt.site"
SOURCE_ROOT = "/opt/kiwoom"
SERVICES = (
    "kiwoom-refresh",
    "moa-dashboard",
    "moa-auto-trading",
    "moa-signal-validation",
    "moa-kakao-notifications",
    "moa-real-performance",
)


def transform(text: str, *, tenant_root: str, origin: str, api_port: int, gateway_port: int) -> str:
    return (
        text.replace(SOURCE_ROOT + "/", tenant_root + "/")
        .replace(OLD_ORIGIN, origin)
        .replace(SOURCE_ORIGIN, origin)
        .replace("8787", str(api_port))
        .replace("8788", str(gateway_port))
    )


def generic_dashboard(text: str) -> str:
    # The captured operator page embeds a personal JPEG in the logo. Replace
    # the entire element rather than trying to sanitize its binary content.
    text, logos = re.subn(
        r'<div class="logo">.*?</div>',
        '<div class="logo"><span>키움 자동매매</span></div>',
        text,
        count=1,
        flags=re.S,
    )
    text, styles = re.subn(r'<style id="ericgolf-brand">.*?</style>', "", text, count=1, flags=re.S)
    text, credits = re.subn(r'<div class="creator-credit"[^>]*>.*?</div>', "", text, count=1, flags=re.S)
    if (logos, styles, credits) != (1, 1, 1):
        raise ValueError("operator-specific dashboard elements changed; review source")
    if text.count("0000-0000") != 1 or text.count("5190-1567") != 1:
        raise ValueError("operator account labels changed; review source")
    return text.replace("0000-0000", "연결 전").replace("5190-1567", "연결 전")


def build(source: Path, output: Path, tenant_id: str, origin: str, api_port: int, gateway_port: int) -> None:
    if not re.fullmatch(r"[a-z][a-z0-9-]{2,20}", tenant_id):
        raise ValueError("tenant ID must be a short lowercase slug")
    parsed = urlparse(origin)
    if parsed.scheme != "https" or not parsed.hostname or parsed.port or parsed.path not in ("", "/"):
        raise ValueError("origin must be a bare HTTPS hostname")
    if origin in (SOURCE_ORIGIN, OLD_ORIGIN):
        raise ValueError("the pilot must not use the operator's domain")
    if api_port == gateway_port or any(port in (80, 443, 8787, 8788) or not 1024 <= port <= 65535 for port in (api_port, gateway_port)):
        raise ValueError("pilot ports must be distinct, unprivileged, and unused by production")
    if output.exists():
        raise FileExistsError("output path already exists; refusing to overwrite")
    tenant_root = f"/opt/kiwoom-tenants/{tenant_id}"
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="tenant-candidate-", dir=output.parent) as temporary:
        candidate = Path(temporary) / "bundle"
        (candidate / "current").mkdir(parents=True)
        (candidate / "root").mkdir()
        (candidate / "dashboard/dist").mkdir(parents=True)
        (candidate / "config/systemd").mkdir(parents=True)
        for path in (source / "current").glob("*.py"):
            if path.name.startswith("test_") or path.name.startswith("patch_") or "diagnostic" in path.name:
                continue
            content = transform(path.read_text(), tenant_root=tenant_root, origin=origin, api_port=api_port, gateway_port=gateway_port)
            ast.parse(content, filename=path.name)
            (candidate / "current" / path.name).write_text(content)
        gateway = Path(__file__).with_name("tenant_gateway.py")
        gateway_text = transform(gateway.read_text(), tenant_root=tenant_root, origin=origin, api_port=api_port, gateway_port=gateway_port)
        ast.parse(gateway_text, filename=gateway.name)
        (candidate / "root/dashboard_gateway.py").write_text(gateway_text)
        for support in ("tenant_auth.py", "invite_user.py"):
            support_text = transform(Path(__file__).with_name(support).read_text(), tenant_root=tenant_root, origin=origin, api_port=api_port, gateway_port=gateway_port)
            ast.parse(support_text, filename=support)
            (candidate / "root" / support).write_text(support_text)
        page = source / "dashboard/dist/index.html"
        page_text = transform(generic_dashboard(page.read_text()), tenant_root=tenant_root, origin=origin, api_port=api_port, gateway_port=gateway_port)
        (candidate / "dashboard/dist/index.html").write_text(page_text)
        shutil.copy2(source / "dashboard/dist/stock-list.js", candidate / "dashboard/dist/stock-list.js")
        caddy_source = (source / "config/Caddyfile").read_text()
        if caddy_source.count("example.invalid {") != 1:
            raise ValueError("source Caddy host changed; review source")
        caddy_source = caddy_source.replace("example.invalid {", parsed.hostname + " {", 1)
        caddy_text = transform(caddy_source, tenant_root=tenant_root, origin=origin, api_port=api_port, gateway_port=gateway_port)
        (candidate / "config/Caddyfile").write_text(caddy_text)
        for name in SERVICES:
            unit = source / "config/systemd" / f"{name}.service"
            content = transform(unit.read_text(), tenant_root=tenant_root, origin=origin, api_port=api_port, gateway_port=gateway_port)
            for service in SERVICES:
                content = content.replace(f"{service}.service", f"{service}@{tenant_id}.service")
            content = content.replace("User=ubuntu", f"User=kiwoom-{tenant_id}")
            if "\nUser=" not in content:
                content = content.replace("[Service]\n", f"[Service]\nUser=kiwoom-{tenant_id}\n", 1)
            (candidate / "config/systemd" / f"{name}@{tenant_id}.service").write_text(content)
        # The existing refresh service has a drop-in allowing state writes.
        # Fold that permission into this standalone pilot unit.
        refresh = candidate / "config/systemd" / f"kiwoom-refresh@{tenant_id}.service"
        refresh_text = refresh.read_text().replace("ReadOnlyPaths=" + tenant_root + "/current " + tenant_root + "/secrets", "ReadOnlyPaths=" + tenant_root + "/current " + tenant_root + "/secrets\nReadWritePaths=" + tenant_root + "/state")
        if "ReadWritePaths=" + tenant_root + "/state" not in refresh_text:
            raise ValueError("refresh service state-write permission not rendered")
        refresh.write_text(refresh_text)
        issues = inspect(candidate, origin)
        if issues:
            raise ValueError("candidate blocked: " + "; ".join(issues))
        for path in candidate.rglob("*.py"):
            if SOURCE_ROOT + "/" in path.read_text() or SOURCE_ORIGIN in path.read_text():
                raise ValueError(f"operator path or URL remains in {path.relative_to(candidate)}")
        candidate.rename(output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("server-baseline"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--origin", required=True)
    parser.add_argument("--api-port", type=int, required=True)
    parser.add_argument("--gateway-port", type=int, required=True)
    args = parser.parse_args()
    build(args.source, args.output, args.tenant_id, args.origin, args.api_port, args.gateway_port)
    print(f"Candidate created at {args.output}; review before any server installation")


if __name__ == "__main__":
    main()
