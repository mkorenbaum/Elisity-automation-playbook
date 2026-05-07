#!/usr/bin/env python3
"""
apply_pg.py — create or update Policy Groups from policy-groups.yaml.

Handles the v2 condition_blocks schema: each PG has an OR-of-AND model
where condition_blocks are ORed and conditions within each block are ANDed.

Maps YAML conditions to CCC matchingCriteria.conditionBlocks[].conditions[]:
  {attribute, operator, values} → {attributeFqdn, operator, attributeType, value}

Resolves PG label names to IDs via the CCC PG label API.
Idempotent: existing PGs matched by name are skipped (create-only).
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
    body_path = "/tmp/.apply-pg-body.json"
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


def ccc_put(creds: dict, token: str, path: str, body: dict) -> Any:
    """PUT for in-place PG updates.

    PG update endpoint is `/api/policy-group/v2/policy-groups/{id}` —
    note the prefix differs from the POST/list path which is
    `/api/policy/v2/policy-groups`. Verified 2026-05-07.
    """
    base = creds["ccc_url"].rstrip("/")
    body_path = "/tmp/.apply-pg-put.json"
    with open(body_path, "w") as f:
        json.dump(body, f)
    proc = subprocess.run(
        ["python3", str(CCC_PY), "call", "--method", "PUT",
         "--token", token, "--body-file", body_path,
         "--accept-status", "200,204",
         f"{base}{path}"],
        text=True, capture_output=True, check=True,
    )
    os.unlink(body_path)
    if proc.stdout.strip():
        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError:
            return None
    return None


def _block_signature(blocks: list[dict]) -> str:
    """Canonical key for conditionBlocks comparison — order-independent."""
    canon = []
    for block in blocks:
        conds = block.get("conditions", []) or []
        norm_conds = []
        for c in conds:
            norm_conds.append({
                "attr": c.get("attributeFqdn") or c.get("attribute"),
                "op": c.get("operator"),
                "vals": sorted(c.get("value") or c.get("values") or []),
            })
        canon.append(sorted(norm_conds, key=lambda x: (x.get("attr") or "")))
    return json.dumps(sorted(canon, key=lambda b: json.dumps(b, sort_keys=True)),
                      sort_keys=True)


def resolve_pg_label_ids(creds: dict, token: str, label_names: list[str]) -> list[str]:
    """Resolve PG label names to CCC IDs."""
    listing = ccc_get(creds, token, "/api/policy/v1/policy-group-label") or {}
    items = listing.get("content", []) if isinstance(listing, dict) else listing
    by_name = {lb["name"]: lb["id"] for lb in items}
    ids = []
    for name in label_names:
        if name in by_name:
            ids.append(by_name[name])
        else:
            sys.stderr.write(f"WARNING: PG label '{name}' not found. Run bootstrap first.\n")
    return ids


def build_condition_blocks(match: dict) -> list[dict]:
    """Convert YAML condition_blocks to CCC conditionBlocks format."""
    blocks = []
    for block in match.get("condition_blocks", []):
        conditions = []
        for cond in block.get("conditions", []):
            conditions.append({
                "operator": cond["operator"],
                "attributeFqdn": cond["attribute"],
                "attributeType": "LIST_STRING",
                "value": cond["values"],
            })
        blocks.append({"conditions": conditions})
    return blocks


def main() -> int:
    creds = load_creds()
    pg_doc = yaml.safe_load((REPO_ROOT / "policy-groups.yaml").read_text()) or {}
    policy_groups = pg_doc.get("policy_groups", [])

    if not policy_groups:
        print("## Policy Groups\n\n> _No policy groups declared._")
        return 0

    token = get_token(creds)

    # Build name→id map of existing PGs
    existing = ccc_get(creds, token, "/api/policy/v2/policy-groups?size=500") or {}
    existing_by_name = {pg["name"]: pg for pg in existing.get("content", [])}

    # Resolve PG label names → IDs (all PGs share the same label set)
    all_label_names = set()
    for pg in policy_groups:
        all_label_names.update(pg.get("labels", []))
    label_id_map = {}
    if all_label_names:
        listing = ccc_get(creds, token, "/api/policy/v1/policy-group-label") or {}
        items = listing.get("content", []) if isinstance(listing, dict) else listing
        label_id_map = {lb["name"]: lb["id"] for lb in items}

    created: list[str] = []
    updated: list[str] = []
    skipped: list[str] = []

    for pg in policy_groups:
        name = pg["name"]

        # Resolve label names to IDs
        label_ids = [label_id_map[ln] for ln in pg.get("labels", []) if ln in label_id_map]
        decl_blocks = build_condition_blocks(pg.get("match", {}))

        body = {
            "name": name,
            "description": pg.get("description", "").strip(),
            "policyGroupType": pg.get("type", "DYNAMIC"),
            "genre": pg.get("genre", "None"),
            "securityLevel": pg.get("security_level", 1),
            "autoLockDevices": pg.get("auto_lock_devices", False),
            "labels": label_ids,
            "matchingCriteria": {"conditionBlocks": decl_blocks},
        }

        existing_pg = existing_by_name.get(name)
        if existing_pg is not None:
            # Idempotent UPDATE — when CCC drifted from YAML (e.g. an
            # operator manually changed genre / security level / match
            # criteria in the UI), apply PUTs the PG back to the
            # declared shape.
            live_label_ids = sorted([
                l["id"] if isinstance(l, dict) else l
                for l in (existing_pg.get("labels") or [])
            ])
            live_blocks = (existing_pg.get("matchingCriteria") or {}).get("conditionBlocks", [])
            drift_fields = (
                (existing_pg.get("description") or "").strip() != body["description"]
                or (existing_pg.get("genre") or "None") != body["genre"]
                or existing_pg.get("securityLevel") != body["securityLevel"]
                or live_label_ids != sorted(label_ids)
                or _block_signature(live_blocks) != _block_signature(decl_blocks)
            )
            if not drift_fields:
                skipped.append(name)
                continue
            ccc_put(
                creds, token,
                f"/api/policy-group/v2/policy-groups/{existing_pg['id']}",
                body,
            )
            updated.append(name)
            continue

        ccc_post(creds, token, "/api/policy/v2/policy-groups/dynamic", body)
        created.append(name)

    print("## Policy Groups")
    print()
    print(f"- Created: **{len(created)}**")
    print(f"- Updated (drift reset): **{len(updated)}**")
    print(f"- Already in sync: **{len(skipped)}**")
    if created:
        print("\n### Created")
        for n in created:
            print(f"- `{n}`")
    if updated:
        print("\n### Updated (live state reset to YAML)")
        for n in updated:
            print(f"- `{n}`")
    if skipped:
        print("\n### Already in sync")
        for n in skipped:
            print(f"- `{n}`")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as e:
        sys.stderr.write(f"CCC call failed: {e.stderr}\n")
        sys.exit(2)
