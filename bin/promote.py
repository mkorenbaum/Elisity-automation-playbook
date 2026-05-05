#!/usr/bin/env python3
"""
promote.py — promote demo policies from MONITOR_ONLY to MONITOR_AND_ENFORCE.

Triggered by the release-tag workflow. For every policy listed in
policies.yaml whose monitor_mode is MONITOR_ONLY, fetch the live policy
from CCC and PUT it back with monitorMode=MONITOR_AND_ENFORCE.

Idempotent: policies already in MONITOR_AND_ENFORCE are reported and
skipped. Outputs a markdown summary to stdout (consumed by the workflow
to comment on the release).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CCC_PY = REPO_ROOT / "bin" / "ccc.py"


def load_creds() -> dict[str, str]:
    with open(REPO_ROOT / "creds.yml") as f:
        return yaml.safe_load(f)


def load_group_vars() -> dict[str, Any]:
    with open(REPO_ROOT / "inventory" / "group_vars" / "all.yml") as f:
        return yaml.safe_load(f)


def get_token(creds: dict[str, str]) -> str:
    base = creds["ccc_url"].rstrip("/")
    proc = subprocess.run(
        ["python3", str(CCC_PY), "token",
         f"{base}/auth/realms/elisity/protocol/openid-connect/token",
         creds["ccc_client_id"], "-"],
        input=creds["ccc_client_secret"],
        text=True, capture_output=True, check=True,
    )
    return proc.stdout.strip()


def ccc_get(creds: dict[str, str], token: str, path: str) -> Any:
    base = creds["ccc_url"].rstrip("/")
    proc = subprocess.run(
        ["python3", str(CCC_PY), "call", "--token", token, f"{base}{path}"],
        text=True, capture_output=True, check=True,
    )
    return json.loads(proc.stdout)


def ccc_put(creds: dict[str, str], token: str, path: str, body: dict) -> Any:
    base = creds["ccc_url"].rstrip("/")
    body_path = "/tmp/.promote-body.json"
    with open(body_path, "w") as f:
        json.dump(body, f)
    proc = subprocess.run(
        ["python3", str(CCC_PY), "call", "--method", "PUT",
         "--token", token, "--body-file", body_path,
         f"{base}{path}"],
        text=True, capture_output=True, check=True,
    )
    os.unlink(body_path)
    if proc.stdout.strip():
        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError:
            return proc.stdout
    return None


def main() -> int:
    creds = load_creds()
    gv = load_group_vars()
    policy_set_id = gv["ccc_policy_set_id"]
    sp_id = gv["ccc_security_profile_id"]

    with open(REPO_ROOT / "policies.yaml") as f:
        policies_doc = yaml.safe_load(f) or {}
    managed_policies = policies_doc.get("policies", [])

    if not managed_policies:
        print("## 🚀 Promotion — nothing to do")
        print("\n_No policies in `policies.yaml`._")
        return 0

    token = get_token(creds)

    # Fetch all policies in the target Policy Set, build a name→object map
    base = creds["ccc_url"].rstrip("/")
    listing = ccc_get(
        creds, token,
        f"/api/policy/v1/policy-sets/{policy_set_id}/policies?size=1000",
    )
    live_by_name = {p["name"]: p for p in listing.get("content", [])}

    promoted: list[str] = []
    already: list[str] = []
    missing: list[str] = []

    for managed in managed_policies:
        name = managed["name"]
        live = live_by_name.get(name)
        if not live:
            missing.append(name)
            continue
        if live.get("monitorMode") == "MONITOR_AND_ENFORCE":
            already.append(name)
            continue

        # Build update payload — server expects same shape minus src/dst PG
        update_body = {
            "name": live["name"],
            "description": live.get("description", ""),
            "monitorMode": "MONITOR_AND_ENFORCE",
            "securityProfiles": [sp_id],
            "finalAction": sp_id,
            "isMirrored": live.get("isMirrored", False),
            "isCustomName": False,
        }
        ccc_put(
            creds, token,
            f"/api/policy/v1/policy-sets/{policy_set_id}/policies/{live['id']}",
            update_body,
        )
        promoted.append(name)

    # Markdown report
    print("## 🚀 Policy Promotion — `MONITOR_ONLY` → `MONITOR_AND_ENFORCE`")
    print()
    print(f"- ✅ Promoted: **{len(promoted)}**")
    print(f"- ⏭️ Already enforcing: **{len(already)}**")
    print(f"- ❌ Missing in CCC: **{len(missing)}**")
    print()
    if promoted:
        print("### Promoted")
        for n in promoted:
            print(f"- `{n}`")
    if already:
        print("\n### Already enforcing (no change)")
        for n in already:
            print(f"- `{n}`")
    if missing:
        print("\n### Missing in CCC (run `make demo` first)")
        for n in missing:
            print(f"- `{n}`")

    return 0 if not missing else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as e:
        sys.stderr.write(f"CCC call failed: {e.stderr}\n")
        sys.exit(2)
