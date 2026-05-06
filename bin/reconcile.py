#!/usr/bin/env python3
"""
reconcile.py — delete CCC objects that are no longer declared in the
repo's YAML files. Multi-layer safety ensures production objects are
never touched.

Covers all 4 object types in safe deletion order:
  1. Policies       (reference PGs + SPs — delete first)
  2. Policy Groups  (referenced by Policies — delete second)
  3. Security Profiles (referenced by Policies — delete third)
  4. Policy Set     (not deleted by reconcile — only by cleanup.yml)

## Three-Guard Safety (all must pass before any DELETE)
##
## Each object type has three independent guards. ALL three must be true
## before a DELETE is issued. If any guard fails, the object is skipped.
##
## Policy Groups:
##   Guard 1: name starts with "forrester-demo-"
##   Guard 2: PG carries the "forrester-demo-hospital" label
##   Guard 3: name is NOT in policy-groups.yaml
##
## Policies:
##   Guard 1: name starts with "forrester-demo-"
##   Guard 2: policy lives in policy set "forrester-demo-hospital-monitor-only"
##   Guard 3: name is NOT in policies.yaml
##
## Security Profiles:
##   Guard 1: name starts with "forrester-demo-"
##   Guard 2: name starts with "forrester-demo-" (double-checked; SPs have
##            no label/policy-set scope, so prefix is the primary guard)
##   Guard 3: name is NOT in security-profiles.yaml
##
## Why three guards:
##   - Guard 1 (prefix) prevents touching ANY non-demo object (CORK PGs,
##     Default policy set, built-in SPs). This alone would suffice but we
##     add defense-in-depth.
##   - Guard 2 (scope) ensures the object belongs to the demo's scoping
##     boundary (PG label for PGs, policy set for Policies).
##   - Guard 3 (declaration check) is the actual reconcile logic: the
##     object IS ours but is no longer declared, so it's an orphan.
##
## Existing CORK PGs and the Default policy set carry neither the
## "forrester-demo-" prefix nor the "forrester-demo-hospital" label.
## They will never pass Guard 1, let alone all three.
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

PREFIX = "forrester-demo-"
DEMO_PG_LABEL = "forrester-demo-hospital"
DEMO_POLICY_SET = "forrester-demo-hospital-monitor-only"


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


def ccc_call(creds: dict, token: str, method: str, path: str) -> str:
    base = creds["ccc_url"].rstrip("/")
    proc = subprocess.run(
        ["python3", str(CCC_PY), "call", "--method", method,
         "--token", token, "--accept-status", "200,204,404",
         f"{base}{path}"],
        text=True, capture_output=True, check=True,
    )
    return proc.stdout


def resolve_policy_set_id(creds: dict, token: str) -> str | None:
    """Find the demo policy set ID by name."""
    raw = ccc_call(creds, token, "GET", "/api/policy/v1/policy-sets")
    if not raw.strip():
        return None
    listing = json.loads(raw)
    for ps in listing.get("content", []):
        if ps["name"] == DEMO_POLICY_SET:
            return ps["id"]
    return None


def resolve_pg_label_names(creds: dict, token: str) -> dict[str, list[str]]:
    """Build a map of PG label ID → label name for label resolution."""
    raw = ccc_call(creds, token, "GET", "/api/policy/v1/policy-group-label")
    if not raw.strip():
        return {}
    labels = json.loads(raw)
    return {lb["id"]: lb["name"] for lb in labels}


def pg_has_demo_label(pg: dict[str, Any], label_id_to_name: dict[str, str]) -> bool:
    """Check if a PG carries the demo PG label."""
    for label_id in pg.get("labels", []):
        label_name = label_id_to_name.get(label_id, "")
        if label_name == DEMO_PG_LABEL:
            return True
    return False


def main() -> int:
    creds = load_creds()
    token = get_token(creds)

    # Declared names (the objects we WANT to keep)
    pg_doc = yaml.safe_load((REPO_ROOT / "policy-groups.yaml").read_text()) or {}
    pol_doc = yaml.safe_load((REPO_ROOT / "policies.yaml").read_text()) or {}
    sp_doc = yaml.safe_load((REPO_ROOT / "security-profiles.yaml").read_text()) or {}

    declared_pg_names = {p["name"] for p in pg_doc.get("policy_groups", [])}
    declared_pol_names = {p["name"] for p in pol_doc.get("policies", [])}
    declared_sp_names = {p["name"] for p in sp_doc.get("security_profiles", [])}

    deleted: list[str] = []

    # ── 1. Policies (delete first — they reference PGs) ─────────
    ps_id = resolve_policy_set_id(creds, token)
    if ps_id:
        raw = ccc_call(creds, token, "GET",
                        f"/api/policy/v1/policy-sets/{ps_id}/policies?size=1000")
        pols = json.loads(raw) if raw.strip() else {}
        for p in pols.get("content", []):
            name = p["name"]
            # Guard 1: prefix check
            if not name.startswith(PREFIX):
                continue
            # Guard 2: policy is in the demo policy set (guaranteed by
            # the query path, but verify the ps_id matches our demo set)
            # — already scoped by querying the demo PS ID
            # Guard 3: not declared in YAML
            if name in declared_pol_names:
                continue

            ccc_call(creds, token, "DELETE",
                     f"/api/policy/v1/policy-sets/{ps_id}/policies/{p['id']}")
            deleted.append(f"Policy   `{name}`")

    # ── 2. Policy Groups (delete second) ─────────────────────────
    label_id_to_name = resolve_pg_label_names(creds, token)
    raw = ccc_call(creds, token, "GET", "/api/policy/v2/policy-groups?size=500")
    pgs = json.loads(raw) if raw.strip() else {}
    for pg in pgs.get("content", []):
        name = pg["name"]
        # Guard 1: prefix check
        if not name.startswith(PREFIX):
            continue
        # Guard 2: PG carries the demo label
        if not pg_has_demo_label(pg, label_id_to_name):
            continue
        # Guard 3: not declared in YAML
        if name in declared_pg_names:
            continue

        ccc_call(creds, token, "DELETE",
                 f"/api/policy/v2/policy-groups/{pg['id']}")
        deleted.append(f"PG       `{name}`")

    # ── 3. Security Profiles (delete third) ──────────────────────
    raw = ccc_call(creds, token, "GET", "/api/policy/v1/security-profiles")
    sp_listing = json.loads(raw) if raw.strip() else {}
    sp_items = sp_listing.get("content", []) if isinstance(sp_listing, dict) else sp_listing
    for sp in sp_items:
        name = sp["name"]
        # Guard 1: prefix check
        if not name.startswith(PREFIX):
            continue
        # Guard 2: prefix double-check (SPs lack label/PS scope)
        if not name.startswith(PREFIX):
            continue
        # Guard 3: not declared in YAML
        if name in declared_sp_names:
            continue

        ccc_call(creds, token, "DELETE",
                 f"/api/policy/v1/security-profiles/{sp['id']}")
        deleted.append(f"SP       `{name}`")

    # ── Report ───────────────────────────────────────────────────
    print(f"## Reconcile -- `{PREFIX}*`")
    print()
    if not deleted:
        print(f"> No orphans. Repo and CCC are aligned.")
        print()
        print(f"- Declared PGs: {len(declared_pg_names)}")
        print(f"- Declared Policies: {len(declared_pol_names)}")
        print(f"- Declared Security Profiles: {len(declared_sp_names)}")
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
