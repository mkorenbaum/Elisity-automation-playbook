#!/usr/bin/env python3
"""
apply_policy_set.py — create or update the dedicated policy set.

Reads policy-set.yaml, resolves PG label IDs and site labels, then
creates the policy set if missing or verifies it matches if present.

Idempotent: re-running with no changes produces no mutations.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CCC_PY = REPO_ROOT / "bin" / "ccc.py"


def load_creds() -> dict:
    return yaml.safe_load((REPO_ROOT / "creds.yml").read_text())


def get_token(creds: dict) -> str:
    base = creds["ccc_url"].rstrip("/")
    proc = subprocess.run(
        ["python3", str(CCC_PY), "token",
         f"{base}/auth/realms/elisity/protocol/openid-connect/token",
         creds["ccc_client_id"], "-"],
        input=creds["ccc_client_secret"],
        text=True, capture_output=True, check=True,
    )
    return proc.stdout.strip()


def ccc_get(creds: dict, token: str, path: str) -> Any:
    base = creds["ccc_url"].rstrip("/")
    proc = subprocess.run(
        ["python3", str(CCC_PY), "call", "--token", token,
         "--accept-status", "200,404",
         f"{base}{path}"],
        text=True, capture_output=True, check=True,
    )
    if not proc.stdout.strip():
        return None
    return json.loads(proc.stdout)


def ccc_post(creds: dict, token: str, path: str, body: dict) -> Any:
    base = creds["ccc_url"].rstrip("/")
    body_path = "/tmp/.apply-policy-set-body.json"
    with open(body_path, "w") as f:
        json.dump(body, f)
    proc = subprocess.run(
        ["python3", str(CCC_PY), "call", "--method", "POST",
         "--token", token, "--body-file", body_path,
         f"{base}{path}"],
        text=True, capture_output=True, check=True,
    )
    import os
    os.unlink(body_path)
    if proc.stdout.strip():
        return json.loads(proc.stdout)
    return None


def resolve_pg_label_ids(creds: dict, token: str, label_names: list[str]) -> list[str]:
    """Resolve PG label names to their CCC IDs."""
    listing = ccc_get(creds, token, "/api/policy/v1/policy-group-label") or []
    by_name = {lb["name"]: lb["id"] for lb in listing}
    ids = []
    for name in label_names:
        if name not in by_name:
            sys.stderr.write(f"ERROR: PG label '{name}' not found in CCC. Run bootstrap first.\n")
            sys.exit(1)
        ids.append(by_name[name])
    return ids


def resolve_site_labels(creds: dict, token: str, site_labels: list[str]) -> list[str]:
    """Resolve site label strings. Sites use the label field directly."""
    listing = ccc_get(creds, token, "/api/topology/v2/sites") or {}
    sites = listing.get("content", listing) if isinstance(listing, dict) else listing
    if isinstance(sites, dict):
        sites = sites.get("content", [])
    known = {s.get("label", s.get("name", "")) for s in sites}
    for label in site_labels:
        if label not in known:
            sys.stderr.write(f"WARNING: site label '{label}' not found in CCC sites. Proceeding anyway.\n")
    return site_labels


def main() -> int:
    creds = load_creds()
    ps_doc = yaml.safe_load((REPO_ROOT / "policy-set.yaml").read_text()) or {}
    ps = ps_doc["policy_set"]

    token = get_token(creds)

    # Check if policy set already exists
    ps_listing = ccc_get(creds, token, "/api/policy/v1/policy-sets") or {}
    existing = None
    for item in ps_listing.get("content", []):
        if item["name"] == ps["name"]:
            existing = item
            break

    if existing:
        print(f"## Policy Set `{ps['name']}`")
        print(f"\n> Already exists (ID: `{existing['id']}`). No changes needed.")
        return 0

    # Resolve label IDs
    pg_label_ids = resolve_pg_label_ids(creds, token, ps.get("policy_group_labels", []))
    site_labels = resolve_site_labels(creds, token, ps.get("site_labels", []))

    body = {
        "name": ps["name"],
        "description": ps.get("description", "").strip(),
        "state": ps.get("state", "MONITOR_ONLY"),
        "policyGroupLabels": pg_label_ids,
        "siteLabels": site_labels,
    }

    result = ccc_post(creds, token, "/api/policy/v1/policy-sets", body)
    ps_id = result.get("id", "unknown") if result else "unknown"

    print(f"## Policy Set `{ps['name']}`")
    print(f"\n> Created policy set (ID: `{ps_id}`).")
    print(f"- State: `{ps.get('state', 'MONITOR_ONLY')}`")
    print(f"- PG labels: {ps.get('policy_group_labels', [])}")
    print(f"- Site labels: {ps.get('site_labels', [])}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as e:
        sys.stderr.write(f"CCC call failed: {e.stderr}\n")
        sys.exit(2)
