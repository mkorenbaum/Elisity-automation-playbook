#!/usr/bin/env python3
"""
reconcile.py — delete CCC objects matching a prefix that are no longer
declared in the repo's YAML.

Used by apply.yml after the create-or-update step. This is what makes
the GitOps loop two-way: removing a Policy Group entry from
policy-groups.yaml in a PR, then merging, will actually delete it from
CCC. Without this step the YAML and CCC silently diverge whenever a
declaration is removed.

Safety: scoped to objects with names starting with the given prefix
(default "forrester-demo-"). Will never touch a PG / Policy whose name
doesn't start with that prefix — production policies are never at risk.
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

    # Names declared in the repo (the ones we WANT to keep)
    pg_doc = yaml.safe_load((REPO_ROOT / "policy-groups.yaml").read_text()) or {}
    pol_doc = yaml.safe_load((REPO_ROOT / "policies.yaml").read_text()) or {}
    declared_pg_names = {p["name"] for p in pg_doc.get("policy_groups", [])}
    declared_pol_names = {p["name"] for p in pol_doc.get("policies", [])}

    token = get_token(creds)
    deleted: list[str] = []

    # ---------- Policies first (they reference PGs by ID) ----------
    pols = json.loads(ccc_call(
        creds, token, "GET",
        f"/api/policy/v1/policy-sets/{policy_set_id}/policies?size=1000",
    ))
    for p in pols.get("content", []):
        name = p["name"]
        if name.startswith(prefix) and name not in declared_pol_names:
            ccc_call(
                creds, token, "DELETE",
                f"/api/policy/v1/policy-sets/{policy_set_id}/policies/{p['id']}",
            )
            deleted.append(f"Policy   `{name}`")

    # ---------- Then Policy Groups ----------
    pgs = json.loads(ccc_call(
        creds, token, "GET",
        "/api/policy/v2/policy-groups?size=500",
    ))
    for pg in pgs.get("content", []):
        name = pg["name"]
        if name.startswith(prefix) and name not in declared_pg_names:
            ccc_call(
                creds, token, "DELETE",
                f"/api/policy/v2/policy-groups/{pg['id']}",
            )
            deleted.append(f"PG       `{name}`")

    print(f"## 🔄 Reconcile — `{prefix}*`")
    print()
    if not deleted:
        print(f"> ✅ No orphans. Repo and CCC are aligned.")
        print()
        print(f"- Declared PGs: {len(declared_pg_names)}")
        print(f"- Declared Policies: {len(declared_pol_names)}")
        return 0
    print(f"Deleted **{len(deleted)}** orphan(s) (in CCC, not in repo):")
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
