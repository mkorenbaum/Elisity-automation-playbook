#!/usr/bin/env python3
"""
reconcile.py — delete CCC objects that are no longer declared in the
repo's YAML files. Two-guard safety per object type ensures production
objects are never touched.

Covers all 4 object types in safe deletion order:
  1. Policies          (reference PGs + SPs — delete first)
  2. Policy Groups     (referenced by Policies — delete second)
  3. Security Profiles (referenced by Policies — delete third)
  4. Policy Set        (not deleted by reconcile — only by cleanup.yml)

## Two-Guard Safety (BOTH must pass before any DELETE)
##
## Policy Groups (clean functional names — no name prefix):
##   Guard 1: PG carries the FORRESTER-DEMO label
##   Guard 2: name is NOT in policy-groups.yaml
##   ↳ CORK PGs survive: they don't carry the FORRESTER-DEMO label.
##
## Policies:
##   Guard 1: policy is inside the FRSTR-HOSPITAL-MONITOR-ONLY policy set
##   Guard 2: name is NOT in policies.yaml
##   ↳ Implicit by querying only the demo policy set; CORK / Default /
##     Demo policy set policies are never enumerated.
##
## Security Profiles:
##   Guard 1: name starts with "FRSTR-"
##   Guard 2: name is NOT in security-profiles.yaml
##   ↳ CCC has no labelling for SPs, so the name prefix is the
##     scoping mechanism for this object type. Built-in SPs
##     (Allow All, Deny All) and OT-flavored SP-* profiles survive.
##
## Why two guards instead of three:
##   The original v1 design used both a name prefix AND a label/PS
##   scope as redundant guards. v2 uses ONE strong scoping mechanism
##   per object type (label for PGs, policy set for Policies, name
##   prefix for SPs) plus the YAML-declaration check. The label and
##   policy-set boundaries are themselves explicit demo-managed
##   markers — no real production object will be tagged FORRESTER-DEMO
##   or live inside FRSTR-HOSPITAL-MONITOR-ONLY by accident.
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

# v2 demo scoping markers
DEMO_PG_LABEL = "FORRESTER-DEMO"                       # PG-label cleanup tag
DEMO_POLICY_SET = "FRSTR-HOSPITAL-MONITOR-ONLY"        # policy set name
SP_PREFIX = "FRSTR-"                                   # security-profile name prefix


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
    items = listing.get("content", []) if isinstance(listing, dict) else listing
    for ps in items:
        if ps.get("name") == DEMO_POLICY_SET:
            return ps["id"]
    return None


def resolve_pg_label_id_to_name(creds: dict, token: str) -> dict[str, str]:
    """Build a map of PG label ID → label name."""
    raw = ccc_call(creds, token, "GET", "/api/policy/v1/policy-group-label")
    if not raw.strip():
        return {}
    listing = json.loads(raw)
    items = listing.get("content", []) if isinstance(listing, dict) else listing
    return {lb["id"]: lb["name"] for lb in items}


def pg_has_demo_label(pg: dict[str, Any], label_id_to_name: dict[str, str]) -> bool:
    """Check whether a PG carries the FORRESTER-DEMO label.

    The PG `labels` field can be either a list of UUIDs or a list of
    {id, name} objects depending on the endpoint version. Handle both.
    """
    for label in pg.get("labels", []):
        if isinstance(label, dict):
            if label.get("name") == DEMO_PG_LABEL:
                return True
        elif isinstance(label, str):
            if label_id_to_name.get(label, "") == DEMO_PG_LABEL:
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
    declared_sp_names = {p["name"] for p in sp_doc.get("security_profiles", [])}
    # Policies are CCC-named "<src> > <dst>" — derive the same names
    # the apply script generates so we match what's actually on the tenant.
    declared_pol_names = {
        f"{p['source_pg']} > {p['destination_pg']}"
        for p in pol_doc.get("policies", [])
    }

    deleted: list[str] = []

    # ── 1. Policies ──────────────────────────────────────────────
    ps_id = resolve_policy_set_id(creds, token)
    if ps_id:
        raw = ccc_call(creds, token, "GET",
                        f"/api/policy/v1/policy-sets/{ps_id}/policies?size=1000")
        pols = json.loads(raw) if raw.strip() else {}
        items = pols.get("content", []) if isinstance(pols, dict) else pols
        for p in items:
            name = p.get("name", "")
            # Guard 1: implicit (we queried the demo PS exclusively)
            # Guard 2: not declared in YAML
            if name in declared_pol_names:
                continue
            # Skip auto-created reflection (Return) policies — they
            # delete with their parent.
            if p.get("isReflection"):
                continue
            ccc_call(creds, token, "DELETE",
                     f"/api/policy/v1/policy-sets/{ps_id}/policies/{p['id']}")
            deleted.append(f"Policy   `{name}`")

    # ── 2. Policy Groups ─────────────────────────────────────────
    label_id_to_name = resolve_pg_label_id_to_name(creds, token)
    raw = ccc_call(creds, token, "GET", "/api/policy/v2/policy-groups?size=500")
    pgs = json.loads(raw) if raw.strip() else {}
    for pg in pgs.get("content", []):
        name = pg["name"]
        # Guard 1: PG carries the demo label
        if not pg_has_demo_label(pg, label_id_to_name):
            continue
        # Guard 2: not declared in YAML
        if name in declared_pg_names:
            continue
        ccc_call(creds, token, "DELETE",
                 f"/api/policy/v2/policy-groups/{pg['id']}")
        deleted.append(f"PG       `{name}`")

    # ── 3. Security Profiles ─────────────────────────────────────
    raw = ccc_call(creds, token, "GET", "/api/policy/v1/security-profiles")
    sp_listing = json.loads(raw) if raw.strip() else {}
    sp_items = sp_listing.get("content", []) if isinstance(sp_listing, dict) else sp_listing
    for sp in sp_items:
        name = sp["name"]
        # Guard 1: name prefix
        if not name.startswith(SP_PREFIX):
            continue
        # Skip CCC-managed reflection SPs (auto-created `<name> Return`
        # copies for bidirectional policies; CCC owns their lifecycle).
        if sp.get("isReflection") or name.endswith(" Return"):
            continue
        # Guard 2: not declared in YAML
        if name in declared_sp_names:
            continue
        ccc_call(creds, token, "DELETE",
                 f"/api/policy/v1/security-profiles/{sp['id']}")
        deleted.append(f"SP       `{name}`")

    # ── Report ───────────────────────────────────────────────────
    print(f"## Reconcile — FORRESTER-DEMO scope")
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
