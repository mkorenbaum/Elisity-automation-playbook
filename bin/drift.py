#!/usr/bin/env python3
"""
drift.py — detect drift between Git source-of-truth and live CCC state.

Triggered hourly by .github/workflows/drift-check.yml. For every Policy
Group and Policy declared in this repo:
  - Does the corresponding object exist in CCC?
  - Do the relevant fields (security level, match criteria, monitor mode,
    description) match?

Exits 0 with "no drift" markdown when everything matches, exit 1 with a
report when drift is detected. The workflow opens / updates a GitHub
issue based on the exit code.
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
        ["python3", str(CCC_PY), "call", "--token", token, f"{base}{path}",
         "--accept-status", "200,404"],
        text=True, capture_output=True, check=True,
    )
    if not proc.stdout.strip():
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None


def declared_pg_signature(pg: dict[str, Any]) -> dict[str, Any]:
    """Pull the fields we control from the YAML declaration."""
    return {
        "policyGroupType": pg.get("type", "DYNAMIC"),
        "securityLevel": pg.get("security_level"),
        "match_attribute": pg["match"]["attribute"],
        "match_operator": pg["match"]["operator"],
        "match_values": sorted(pg["match"]["match_values"]),
    }


def live_pg_signature(live: dict[str, Any]) -> dict[str, Any]:
    crit = live.get("matchingCriteria", {}) or {}
    cond_blocks = crit.get("conditionBlocks", [])
    if cond_blocks and cond_blocks[0].get("conditions"):
        c0 = cond_blocks[0]["conditions"][0]
        match_attr = c0.get("attributeFqdn")
        match_op = c0.get("operator")
        match_vals = sorted(c0.get("value", []))
    else:
        match_attr = match_op = None
        match_vals = []
    return {
        "policyGroupType": live.get("policyGroupType"),
        "securityLevel": live.get("securityLevel"),
        "match_attribute": match_attr,
        "match_operator": match_op,
        "match_values": match_vals,
    }


def resolve_var(value: Any, group_vars: dict[str, Any]) -> Any:
    """Substitute `{{ ccc_* }}` Jinja-style references with values from group_vars.
    Strict-but-tiny: only handles a single var reference per string. Good
    enough for the demo YAML; not a full templating engine."""
    if not isinstance(value, str):
        return value
    s = value.strip()
    if s.startswith("{{") and s.endswith("}}"):
        name = s[2:-2].strip()
        return group_vars.get(name, value)
    return value


def declared_policy_signature(p: dict[str, Any], gv: dict[str, Any]) -> dict[str, Any]:
    return {
        "monitorMode": p.get("monitor_mode"),
        "src": p.get("source_policy_group"),
        "dst_id": resolve_var(p.get("destination_policy_group_id"), gv),
    }


def live_policy_signature(p: dict[str, Any]) -> dict[str, Any]:
    return {
        "monitorMode": p.get("monitorMode"),
        "src": p.get("srcPolicyGroupName"),
        "dst_id": p.get("dstPolicyGroupId"),
    }


def main() -> int:
    creds = load_creds()
    gv = load_group_vars()
    policy_set_id = gv["ccc_policy_set_id"]

    pg_doc = yaml.safe_load((REPO_ROOT / "policy-groups.yaml").read_text()) or {}
    pol_doc = yaml.safe_load((REPO_ROOT / "policies.yaml").read_text()) or {}
    declared_pgs = pg_doc.get("policy_groups", [])
    declared_policies = pol_doc.get("policies", [])

    token = get_token(creds)

    # Fetch live state (best-effort)
    pg_listing = ccc_get(creds, token, "/api/policy/v2/policy-groups?size=500") or {}
    live_pgs_by_name = {p["name"]: p for p in pg_listing.get("content", [])}

    pol_listing = ccc_get(
        creds, token,
        f"/api/policy/v1/policy-sets/{policy_set_id}/policies?size=1000",
    ) or {}
    live_pols_by_name = {p["name"]: p for p in pol_listing.get("content", [])}

    drift_rows: list[str] = []

    # Policy Groups
    for pg in declared_pgs:
        name = pg["name"]
        live = live_pgs_by_name.get(name)
        if not live:
            drift_rows.append(f"| Policy Group | `{name}` | declared in repo, **missing in CCC** |")
            continue
        # Need the full PG (matchingCriteria isn't in the listing)
        full = ccc_get(creds, token, f"/api/policy/v2/policy-groups/{live['id']}")
        if not full:
            drift_rows.append(f"| Policy Group | `{name}` | could not fetch detail |")
            continue
        decl_sig = declared_pg_signature(pg)
        live_sig = live_pg_signature(full)
        if decl_sig != live_sig:
            for k in decl_sig:
                if decl_sig[k] != live_sig[k]:
                    drift_rows.append(
                        f"| Policy Group | `{name}` | "
                        f"`{k}`: repo=`{decl_sig[k]}` ≠ live=`{live_sig[k]}` |"
                    )

    # Policies
    for p in declared_policies:
        name = p["name"]
        live = live_pols_by_name.get(name)
        if not live:
            drift_rows.append(f"| Policy | `{name}` | declared in repo, **missing in CCC** |")
            continue
        decl_sig = declared_policy_signature(p, gv)
        live_sig = live_policy_signature(live)
        # Allow MONITOR_AND_ENFORCE if repo says MONITOR_ONLY (post-promotion)
        if decl_sig["monitorMode"] == "MONITOR_ONLY" and live_sig["monitorMode"] == "MONITOR_AND_ENFORCE":
            decl_sig["monitorMode"] = "MONITOR_AND_ENFORCE"
        if decl_sig != live_sig:
            for k in decl_sig:
                if decl_sig[k] != live_sig[k]:
                    drift_rows.append(
                        f"| Policy | `{name}` | "
                        f"`{k}`: repo=`{decl_sig[k]}` ≠ live=`{live_sig[k]}` |"
                    )

    print("## 🔁 Drift Check — Git source-of-truth vs CCC live state")
    print()
    print(f"_Tenant: `{creds['ccc_url']}`. Time: GitHub Action run._")
    print()
    if not drift_rows:
        print("> ✅ **No drift.** CCC is in sync with `main`.")
        print()
        print(f"- Policy Groups checked: {len(declared_pgs)}")
        print(f"- Policies checked: {len(declared_policies)}")
        return 0

    print(f"> ⚠️ **Drift detected** in {len(drift_rows)} field(s).")
    print()
    print("| Object | Name | Drift |")
    print("|---|---|---|")
    for row in drift_rows:
        print(row)
    print()
    print("**To resolve:**")
    print("- If the live tenant change was intentional, update this repo "
          "(open a PR with the new YAML) so the source-of-truth catches up.")
    print("- If the live tenant change was unintentional, manually re-run "
          "the `apply` workflow (or run `make demo` locally) to push the "
          "repo state back to CCC.")
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as e:
        sys.stderr.write(f"CCC call failed: {e.stderr}\n")
        sys.exit(2)
