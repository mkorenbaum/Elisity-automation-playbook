#!/usr/bin/env python3
"""
apply_policy.py — create or update Policies from policies.yaml.

Resolves by name at apply time:
  - source_pg / destination_pg → PG IDs via /api/policy/v2/policy-groups
  - security_profile → SP ID via /api/policy/v1/security-profiles
  - policy_set → PS ID via /api/policy/v1/policy-sets

Maps YAML direction to CCC isMirrored:
  SELF          → isMirrored=false (src==dst)
  BIDIRECTIONAL → isMirrored=true
  UNIDIRECTIONAL→ isMirrored=false

All policies are created in MONITOR_ONLY. Promote.yml flips to enforce.
Idempotent: existing policies matched by name are skipped.
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
    body_path = "/tmp/.apply-policy-body.json"
    with open(body_path, "w") as f:
        json.dump(body, f)
    proc = subprocess.run(
        ["python3", str(CCC_PY), "call", "--method", "POST",
         "--token", token, "--body-file", body_path,
         f"{base}{path}"],
        text=True, capture_output=True, check=True,
    )
    os.unlink(body_path)
    if proc.stdout.strip():
        return json.loads(proc.stdout)
    return None


def resolve_policy_set_id(creds: dict, token: str, ps_name: str) -> str:
    listing = ccc_get(creds, token, "/api/policy/v1/policy-sets") or {}
    for item in listing.get("content", []):
        if item["name"] == ps_name:
            return item["id"]
    sys.stderr.write(f"ERROR: Policy set '{ps_name}' not found. Run bootstrap first.\n")
    sys.exit(1)


def main() -> int:
    creds = load_creds()
    pol_doc = yaml.safe_load((REPO_ROOT / "policies.yaml").read_text()) or {}
    policies = pol_doc.get("policies", [])

    if not policies:
        print("## Policies\n\n> _No policies declared._")
        return 0

    token = get_token(creds)

    # Build name→id maps for PGs, SPs, and the policy set
    pg_listing = ccc_get(creds, token, "/api/policy/v2/policy-groups?size=500") or {}
    pg_by_name = {pg["name"]: pg["id"] for pg in pg_listing.get("content", [])}

    sp_listing = ccc_get(creds, token, "/api/policy/v1/security-profiles") or {}
    sp_items = sp_listing.get("content", []) if isinstance(sp_listing, dict) else sp_listing
    sp_by_name = {sp["name"]: sp["id"] for sp in sp_items}

    # CCC requires `finalAction` on a Policy to be one of the four
    # system Security Profiles: Allow All / Allow All (Log) / Deny All
    # / Deny All (Log). It is NOT the same as `securityProfiles[0]` —
    # securityProfiles holds the L4 rule set the policy applies, while
    # finalAction is the terminal verdict if no rule matches.
    if "Allow All" not in sp_by_name or "Deny All" not in sp_by_name:
        sys.stderr.write("ERROR: CCC tenant is missing built-in Allow All / Deny All system profiles.\n")
        sys.exit(1)
    permit_id = sp_by_name["Allow All"]
    deny_id = sp_by_name["Deny All"]

    # Group policies by policy set
    policies_by_ps: dict[str, list[dict]] = {}
    for pol in policies:
        ps_name = pol.get("policy_set", "Default")
        policies_by_ps.setdefault(ps_name, []).append(pol)

    created: list[str] = []
    skipped: list[str] = []
    errors: list[str] = []

    for ps_name, ps_policies in policies_by_ps.items():
        ps_id = resolve_policy_set_id(creds, token, ps_name)

        # Get existing policies in this policy set
        existing = ccc_get(
            creds, token,
            f"/api/policy/v1/policy-sets/{ps_id}/policies?size=1000",
        ) or {}
        existing_by_name = {p["name"]: p for p in existing.get("content", [])}

        for pol in ps_policies:
            yaml_name = pol["name"]   # YAML name is documentation; CCC needs "<src> > <dst>"

            # Resolve PG names to IDs
            src_pg_name = pol["source_pg"]
            dst_pg_name = pol["destination_pg"]
            sp_name = pol["security_profile"]

            # CCC requires Policy names in the form "<srcPG> > <dstPG>".
            # The YAML field `name` is documentation only — CCC rejects
            # any other format with 400 "different format than expected".
            ccc_name = f"{src_pg_name} > {dst_pg_name}"

            if ccc_name in existing_by_name:
                skipped.append(ccc_name)
                continue

            if src_pg_name not in pg_by_name:
                errors.append(f"`{yaml_name}`: source PG `{src_pg_name}` not found")
                continue
            if dst_pg_name not in pg_by_name:
                errors.append(f"`{yaml_name}`: destination PG `{dst_pg_name}` not found")
                continue
            if sp_name not in sp_by_name:
                errors.append(f"`{yaml_name}`: security profile `{sp_name}` not found")
                continue

            direction = pol.get("direction", "BIDIRECTIONAL")
            is_mirrored = direction == "BIDIRECTIONAL"
            final_action_id = permit_id if pol.get("final_action", "PERMIT") == "PERMIT" else deny_id

            body = {
                "name": ccc_name,
                "description": pol.get("description", "").strip() if pol.get("description") else "",
                "srcPolicyGroup": pg_by_name[src_pg_name],
                "dstPolicyGroup": pg_by_name[dst_pg_name],
                "securityProfiles": [sp_by_name[sp_name]],
                "finalAction": final_action_id,
                "monitorMode": pol.get("state", "MONITOR_ONLY"),
                "isMirrored": is_mirrored,
                "isCustomName": False,
            }

            ccc_post(
                creds, token,
                f"/api/policy/v1/policy-sets/{ps_id}/policies",
                body,
            )
            created.append(ccc_name)

    print("## Policies")
    print()
    print(f"- Created: **{len(created)}**")
    print(f"- Already exist: **{len(skipped)}**")
    if errors:
        print(f"- Errors: **{len(errors)}**")
    if created:
        print("\n### Created")
        for n in created:
            print(f"- `{n}`")
    if skipped:
        print("\n### Skipped (already exist)")
        for n in skipped:
            print(f"- `{n}`")
    if errors:
        print("\n### Errors")
        for e in errors:
            print(f"- {e}")
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as e:
        sys.stderr.write(f"CCC call failed: {e.stderr}\n")
        sys.exit(2)
