#!/usr/bin/env python3
"""
The Elisity demo as a stdlib-only Python script — no SDK, no requests, no
deps. Demonstrates that any environment with python3 (default on macOS
12.3+, every Linux distro, every CI runner) can drive Elisity.

Usage:
  CCC_URL=...           \\
  CCC_CLIENT_ID=...     \\
  CCC_CLIENT_SECRET=... \\
  python3 examples/python-direct.py
"""
from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.parse
import urllib.request


def env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        sys.exit(f"Missing env var: {name}")
    return v


def main() -> int:
    base = env("CCC_URL").rstrip("/")
    cid = env("CCC_CLIENT_ID")
    sec = env("CCC_CLIENT_SECRET")
    ctx = ssl._create_unverified_context()

    # 1. OAuth2 client_credentials → access token
    body = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": cid,
        "client_secret": sec,
        "scope": "openid",
    }).encode()
    req = urllib.request.Request(
        f"{base}/auth/realms/elisity/protocol/openid-connect/token",
        data=body, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, context=ctx, timeout=30) as r:
        token = json.load(r)["access_token"]
    print(f"Authenticated to {base} ({len(token)}-char token).")

    # 2. List connectors
    req = urllib.request.Request(
        f"{base}/api/identity-graph/v1/connector-connectivity",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, context=ctx, timeout=30) as r:
        connectors = json.load(r)
    print(f"\nConnectors configured ({len(connectors)}):")
    for c in connectors:
        print(f"  • {c.get('type', '?'):32s}  status={c.get('status', 'UNKNOWN')}")

    print("\nSee playbooks/ or terraform/ for the full create-and-verify flow.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
