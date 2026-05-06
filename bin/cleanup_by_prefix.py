#!/usr/bin/env python3
"""
cleanup_by_prefix.py — delete every CCC Policy / Policy Group whose name
starts with the given prefix.

Used by .github/workflows/cleanup.yml. Unlike the Ansible cleanup play
this script does NOT depend on a `.state.json` file — it discovers what
to delete by querying CCC directly. Lets us run cleanup from a fresh
GitHub Actions runner that has no prior state.

Usage:
  python3 bin/cleanup_by_prefix.py [prefix]
  (default prefix: "forrester-demo-")
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CCC_PY = REPO_ROOT / "bin" / "ccc.py"


def load_creds() -> dict:
    return yaml.safe_load((REPO_ROOT / "creds.yml").read_text())


def load_group_vars() -> dict:
    return yaml.safe_load((REPO_ROOT / "inventory" / "group_vars" / "all.yml").read_text())


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


def ccc_call(creds: dict, token: str, method: str, path: str) -> str:
    base = creds["ccc_url"].rstrip("/")
    proc = subprocess.run(
        ["python3", str(CCC_PY), "call", "--method", method,
         "--token", token, "--accept-status", "200,204,404",
         f"{base}{path}"],
        text=True, capture_output=True, check=True,
    )
    return proc.stdout


def main() -> int:
    prefix = sys.argv[1] if len(sys.argv) > 1 else "forrester-demo-"
    creds = load_creds()
    gv = load_group_vars()
    policy_set_id = gv["ccc_policy_set_id"]

    token = get_token(creds)
    deleted: list[str] = []

    # Delete policies first — they reference Policy Groups by ID. Doing
    # the reverse order would orphan the Policy.
    pols = json.loads(ccc_call(
        creds, token, "GET",
        f"/api/policy/v1/policy-sets/{policy_set_id}/policies?size=1000",
    ))
    for p in pols.get("content", []):
        if p["name"].startswith(prefix):
            ccc_call(
                creds, token, "DELETE",
                f"/api/policy/v1/policy-sets/{policy_set_id}/policies/{p['id']}",
            )
            deleted.append(f"Policy   `{p['name']}`")

    # Then Policy Groups.
    pgs = json.loads(ccc_call(
        creds, token, "GET",
        "/api/policy/v2/policy-groups?size=500",
    ))
    for pg in pgs.get("content", []):
        if pg["name"].startswith(prefix):
            ccc_call(
                creds, token, "DELETE",
                f"/api/policy/v2/policy-groups/{pg['id']}",
            )
            deleted.append(f"PG       `{pg['name']}`")

    # Markdown summary (consumed by the workflow log + step-summary)
    print(f"## 🧹 Cleanup — `{prefix}*`")
    print()
    if not deleted:
        print("> ✅ Nothing to delete. Tenant already clean.")
        return 0
    print(f"Deleted **{len(deleted)}** object(s):")
    print()
    for line in deleted:
        print(f"- {line}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as e:
        sys.stderr.write(f"CCC call failed: {e.stderr}\n")
        sys.exit(2)
