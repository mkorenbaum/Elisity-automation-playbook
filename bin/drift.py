#!/usr/bin/env python3
"""
drift.py — detect drift between Git source-of-truth and live CCC state
across all 4 object types.

Triggered hourly by .github/workflows/drift-check.yml. Checks:
  1. Policy Set     — exists, state matches
  2. Security Profiles — exist, rule sets match
  3. Policy Groups  — exist, condition blocks + security level match
  4. Policies       — exist, src/dst/SP/mode match

Exits 0 with "no drift" markdown when everything matches, exit 1 when
drift is detected. The workflow opens/updates a GitHub issue accordingly.
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

PROTOCOL_MAP = {"tcp": 6, "udp": 17, "icmp": 1, "any": None}


def load_creds() -> dict[str, str]:
    with open(REPO_ROOT / "creds.yml") as f:
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


# ── Signature extraction for comparison ──────────────────────────

def _stable_key(obj) -> str:
    """Order-independent canonical JSON key for set-like comparison."""
    return json.dumps(obj, sort_keys=True, default=str)


def declared_pg_signature(pg: dict) -> dict:
    """Extract comparable fields from a YAML PG declaration."""
    blocks = []
    for block in pg.get("match", {}).get("condition_blocks", []):
        conds = []
        for c in block.get("conditions", []):
            conds.append({
                "attr": c["attribute"],
                "op": c["operator"],
                "vals": sorted(c["values"]),
            })
        blocks.append(sorted(conds, key=lambda x: x["attr"]))
    # Sort the outer block list too — CCC may return blocks in a different
    # order than the YAML declaration; semantically equivalent, but a
    # naive list compare would flag drift on ordering alone.
    blocks = sorted(blocks, key=_stable_key)
    return {
        "type": pg.get("type", "DYNAMIC"),
        "genre": pg.get("genre", "None"),
        "securityLevel": pg.get("security_level"),
        "conditionBlocks": blocks,
    }


def live_pg_signature(live: dict) -> dict:
    """Extract comparable fields from a live CCC PG."""
    crit = live.get("matchingCriteria", {}) or {}
    blocks = []
    for block in crit.get("conditionBlocks", []):
        conds = []
        for c in block.get("conditions", []):
            conds.append({
                "attr": c.get("attributeFqdn", ""),
                "op": c.get("operator", ""),
                "vals": sorted(c.get("value", [])),
            })
        blocks.append(sorted(conds, key=lambda x: x["attr"]))
    blocks = sorted(blocks, key=_stable_key)
    return {
        "type": live.get("policyGroupType"),
        "genre": live.get("genre", "None"),
        "securityLevel": live.get("securityLevel"),
        "conditionBlocks": blocks,
    }


def _expand_dst_ports(dst: str | None) -> list[str | None]:
    """Comma-separated port lists become multiple rules at apply time
    (gotcha G4 — CCC rejects comma-lists in a single ruleSet entry). Drift
    needs to expand the YAML's "104,11112,11113" into ["104","11112","11113"]
    so the comparison aligns with what's actually on the tenant."""
    if dst is None or str(dst).lower() == "any":
        return [None]
    return [p.strip() for p in str(dst).split(",") if p.strip()]


def declared_sp_signature(sp: dict) -> list[dict]:
    """Extract comparable rule set from YAML SP, expanding comma-port lists."""
    rules = []
    for r in sp.get("rules", []):
        proto_str = r.get("protocol", "any").lower()
        # Match apply path: "any" -> -1; tcp/udp/icmp -> standard nums
        proto = {"tcp": 6, "udp": 17, "icmp": 1, "any": -1}.get(proto_str, -1)
        permit = r.get("action", "permit").lower() == "permit"
        for dst in _expand_dst_ports(r.get("dst_ports", "any")):
            rules.append({
                "protocol": proto,
                "dst": dst,
                "permit": permit,
            })
    return sorted(rules, key=_stable_key)


def live_sp_signature(live: dict) -> list[dict]:
    """Extract comparable rule set from live CCC SP."""
    rules = []
    for rule in live.get("securityRules", []):
        # Live SPs come back with structured port-range objects under
        # securityRules. Match the apply-time write shape: protocol int,
        # dst as a string ("443" or "104-110"), permit as bool.
        dsts = rule.get("destinationPorts") or [{}]
        first = dsts[0] if dsts else {}
        if first.get("any"):
            dst_str = None
        else:
            start = first.get("start")
            end = first.get("end")
            if start is not None and end is not None and start == end:
                dst_str = str(start)
            elif start is not None and end is not None:
                dst_str = f"{start}-{end}"
            else:
                dst_str = None
        rules.append({
            "protocol": rule.get("protocol"),
            "dst": dst_str,
            "permit": rule.get("action", True),
        })
    return sorted(rules, key=_stable_key)


def declared_policy_signature(p: dict) -> dict:
    return {
        "state": p.get("state", "MONITOR_ONLY"),
        "src": p.get("source_pg"),
        "dst": p.get("destination_pg"),
        "sp": p.get("security_profile"),
        "direction": p.get("direction", "BIDIRECTIONAL"),
    }


def live_policy_signature(p: dict, pg_id_to_name: dict, sp_id_to_name: dict) -> dict:
    is_mirrored = p.get("isMirrored", False)
    src_name = p.get("srcPolicyGroupName", "")
    dst_name = p.get("dstPolicyGroupName") or pg_id_to_name.get(p.get("dstPolicyGroupId", ""), "")

    # CCC's policy listing returns `securityProfileName` (singular) and
    # `securityProfileId` directly — not a `securityProfiles` array.
    sp_name = p.get("securityProfileName") or sp_id_to_name.get(p.get("securityProfileId", ""), "")

    if src_name == dst_name:
        direction = "SELF"
    elif is_mirrored:
        direction = "BIDIRECTIONAL"
    else:
        direction = "UNIDIRECTIONAL"

    return {
        "state": p.get("monitorMode", "MONITOR_ONLY"),
        "src": src_name,
        "dst": dst_name,
        "sp": sp_name,
        "direction": direction,
    }


def main() -> int:
    creds = load_creds()
    token = get_token(creds)

    # Load all YAML declarations
    ps_doc = yaml.safe_load((REPO_ROOT / "policy-set.yaml").read_text()) or {}
    sp_doc = yaml.safe_load((REPO_ROOT / "security-profiles.yaml").read_text()) or {}
    pg_doc = yaml.safe_load((REPO_ROOT / "policy-groups.yaml").read_text()) or {}
    pol_doc = yaml.safe_load((REPO_ROOT / "policies.yaml").read_text()) or {}

    declared_ps = ps_doc.get("policy_set", {})
    declared_sps = sp_doc.get("security_profiles", [])
    declared_pgs = pg_doc.get("policy_groups", [])
    declared_policies = pol_doc.get("policies", [])

    drift_rows: list[str] = []

    # ── 1. Policy Set ────────────────────────────────────────────
    ps_listing = ccc_get(creds, token, "/api/policy/v1/policy-sets") or {}
    live_ps = None
    ps_id = None
    for item in ps_listing.get("content", []):
        if item["name"] == declared_ps.get("name"):
            live_ps = item
            ps_id = item["id"]
            break
    if declared_ps.get("name") and not live_ps:
        drift_rows.append(f"| Policy Set | `{declared_ps['name']}` | declared in repo, **missing in CCC** |")

    # ── 2. Security Profiles ─────────────────────────────────────
    sp_listing = ccc_get(creds, token, "/api/policy/v1/security-profiles") or {}
    sp_items = sp_listing.get("content", []) if isinstance(sp_listing, dict) else sp_listing
    live_sps_by_name = {sp["name"]: sp for sp in sp_items}
    sp_id_to_name = {sp["id"]: sp["name"] for sp in sp_items}

    for sp in declared_sps:
        name = sp["name"]
        live = live_sps_by_name.get(name)
        if not live:
            drift_rows.append(f"| Security Profile | `{name}` | declared in repo, **missing in CCC** |")
            continue
        decl_sig = declared_sp_signature(sp)
        live_sig = live_sp_signature(live)
        if decl_sig != live_sig:
            drift_rows.append(f"| Security Profile | `{name}` | rule set differs |")

    # ── 3. Policy Groups ─────────────────────────────────────────
    pg_listing = ccc_get(creds, token, "/api/policy/v2/policy-groups?size=500") or {}
    live_pgs_by_name = {p["name"]: p for p in pg_listing.get("content", [])}
    pg_id_to_name = {p["id"]: p["name"] for p in pg_listing.get("content", [])}

    for pg in declared_pgs:
        name = pg["name"]
        live = live_pgs_by_name.get(name)
        if not live:
            drift_rows.append(f"| Policy Group | `{name}` | declared in repo, **missing in CCC** |")
            continue
        # Fetch full PG detail for matchingCriteria
        full = ccc_get(creds, token, f"/api/policy/v2/policy-groups/{live['id']}")
        if not full:
            drift_rows.append(f"| Policy Group | `{name}` | could not fetch detail |")
            continue
        decl_sig = declared_pg_signature(pg)
        live_sig = live_pg_signature(full)
        if decl_sig != live_sig:
            for k in decl_sig:
                if decl_sig[k] != live_sig.get(k):
                    drift_rows.append(
                        f"| Policy Group | `{name}` | `{k}`: repo != live |"
                    )

    # ── 4. Policies ──────────────────────────────────────────────
    # Three drift signals:
    #   a) declared in repo but missing in CCC
    #   b) field drift on a declared policy (sp / direction / state / src / dst)
    #   c) **orphan** — live in CCC but never declared (out-of-band addition)
    #
    # The state mask (MONITOR_ONLY repo vs MONITOR_AND_ENFORCE live) is only
    # honored when ALL declared policies are flipped — that's the promote.yml
    # signature. A single-policy out-of-band flip fails the count check and
    # raises drift.
    if ps_id:
        pol_listing = ccc_get(
            creds, token,
            f"/api/policy/v1/policy-sets/{ps_id}/policies?size=1000",
        ) or {}
        # Filter out CCC-managed reflection (Return) policies — they're
        # auto-created with bidirectional pairs; CCC owns their lifecycle.
        live_pols = [p for p in pol_listing.get("content", []) if not p.get("isReflection")]
        live_pols_by_name = {p["name"]: p for p in live_pols}

        # CCC names policies "<src> > <dst>"; the YAML `name` field is just
        # documentation. Match on the auto-generated name to match what
        # apply_policy.py creates.
        declared_by_ccc_name: dict[str, dict] = {}
        for p in declared_policies:
            ccc_name = f"{p['source_pg']} > {p['destination_pg']}"
            declared_by_ccc_name[ccc_name] = p

        # State-mask gate: only mask MONITOR_ONLY -> MONITOR_AND_ENFORCE if
        # ALL declared policies are in MONITOR_AND_ENFORCE on the tenant.
        if declared_by_ccc_name:
            promoted = sum(
                1 for n in declared_by_ccc_name
                if (live_pols_by_name.get(n) or {}).get("monitorMode") == "MONITOR_AND_ENFORCE"
            )
            all_promoted = promoted == len(declared_by_ccc_name)
        else:
            all_promoted = False

        # (c) Orphan detection — live policies not declared in YAML
        for live in live_pols:
            if live["name"] not in declared_by_ccc_name:
                drift_rows.append(
                    f"| Policy | `{live['name']}` | **out-of-band addition** (in CCC, not in YAML) |"
                )

        # (a) + (b) — declared policies missing or field-drifted in CCC
        for ccc_name, p in declared_by_ccc_name.items():
            live = live_pols_by_name.get(ccc_name)
            if not live:
                drift_rows.append(f"| Policy | `{ccc_name}` | declared in repo, **missing in CCC** |")
                continue
            decl_sig = declared_policy_signature(p)
            live_sig = live_policy_signature(live, pg_id_to_name, sp_id_to_name)
            if all_promoted and decl_sig["state"] == "MONITOR_ONLY" and live_sig["state"] == "MONITOR_AND_ENFORCE":
                decl_sig["state"] = "MONITOR_AND_ENFORCE"
            if decl_sig != live_sig:
                for k in decl_sig:
                    if decl_sig[k] != live_sig.get(k):
                        drift_rows.append(
                            f"| Policy | `{ccc_name}` | `{k}`: repo=`{decl_sig[k]}` != live=`{live_sig.get(k)}` |"
                        )

    # ── Report ───────────────────────────────────────────────────
    print("## Drift Check -- Git source-of-truth vs CCC live state")
    print()
    print(f"_Tenant: `{creds['ccc_url']}`. Time: GitHub Action run._")
    print()
    if not drift_rows:
        print("> No drift. CCC is in sync with `main`.")
        print()
        print(f"- Policy Set: `{declared_ps.get('name', 'N/A')}`")
        print(f"- Security Profiles checked: {len(declared_sps)}")
        print(f"- Policy Groups checked: {len(declared_pgs)}")
        print(f"- Policies checked: {len(declared_policies)}")
        return 0

    print(f"> Drift detected in {len(drift_rows)} field(s).")
    print()
    print("| Object | Name | Drift |")
    print("|---|---|---|")
    for row in drift_rows:
        print(row)
    print()
    print("**To resolve:**")
    print("- If the live tenant change was intentional, update this repo "
          "(open a PR with the new YAML) so the source-of-truth catches up.")
    print("- If the live tenant change was unintentional, re-run "
          "the `apply` workflow to push the repo state back to CCC.")
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as e:
        sys.stderr.write(f"CCC call failed: {e.stderr}\n")
        sys.exit(2)
