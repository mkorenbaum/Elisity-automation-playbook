#!/usr/bin/env python3
"""
bootstrap.py — idempotent first-run setup for the Forrester demo.

Creates (if missing) in dependency order:
  1. Policy Group Label  — `forrester-demo-hospital`
  2. Policy Set          — `forrester-demo-hospital-monitor-only`
  3. Security Profiles   — all entries from security-profiles.yaml

Idempotent: re-running after a successful bootstrap produces zero
mutations. Each object is looked up by name before creating.

Prints resolved IDs as a YAML fragment suitable for caching in
inventory/group_vars/all.yml.
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

PROTOCOL_MAP = {"tcp": 6, "udp": 17, "icmp": 1, "any": None}


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
    body_path = "/tmp/.bootstrap-body.json"
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


def build_rule_set(rules: list[dict]) -> list[dict]:
    """Convert YAML rules to CCC ruleSet format."""
    result = []
    for rule in rules:
        proto_str = rule.get("protocol", "any").lower()
        proto_num = PROTOCOL_MAP.get(proto_str)
        dst_ports = rule.get("dst_ports", "any")
        if dst_ports == "any":
            dst_ports = None
        src_ports = rule.get("src_ports", "any")
        if src_ports == "any":
            src_ports = None
        is_permit = rule.get("action", "permit").lower() == "permit"

        prop: dict[str, Any] = {"permit": is_permit}
        if proto_num is not None:
            prop["protocol"] = proto_num
        if dst_ports is not None:
            prop["destinationPorts"] = str(dst_ports)
        if src_ports is not None:
            prop["sourcePorts"] = str(src_ports)
        result.append({"property": prop})
    return result


def main() -> int:
    creds = load_creds()
    ps_doc = yaml.safe_load((REPO_ROOT / "policy-set.yaml").read_text()) or {}
    sp_doc = yaml.safe_load((REPO_ROOT / "security-profiles.yaml").read_text()) or {}

    ps_def = ps_doc["policy_set"]
    pg_labels_def = ps_doc.get("policy_group_labels", [])
    sp_defs = sp_doc.get("security_profiles", [])

    token = get_token(creds)
    actions: list[str] = []

    # ── 1. Policy Group Label ────────────────────────────────────
    label_listing = ccc_get(creds, token, "/api/policy/v1/policy-group-label") or []
    label_by_name = {lb["name"]: lb for lb in label_listing}

    pg_label_ids: dict[str, str] = {}
    for lbl in pg_labels_def:
        name = lbl["name"]
        if name in label_by_name:
            pg_label_ids[name] = label_by_name[name]["id"]
            actions.append(f"PG label `{name}`: already exists (ID: `{pg_label_ids[name]}`)")
        else:
            result = ccc_post(creds, token, "/api/policy/v1/policy-group-label", {
                "name": name,
                "description": lbl.get("description", "").strip(),
            })
            lid = result.get("id", "unknown") if result else "unknown"
            pg_label_ids[name] = lid
            actions.append(f"PG label `{name}`: **created** (ID: `{lid}`)")

    # ── 2. Policy Set ────────────────────────────────────────────
    ps_listing = ccc_get(creds, token, "/api/policy/v1/policy-sets") or {}
    ps_by_name = {p["name"]: p for p in ps_listing.get("content", [])}

    ps_name = ps_def["name"]
    if ps_name in ps_by_name:
        ps_id = ps_by_name[ps_name]["id"]
        actions.append(f"Policy set `{ps_name}`: already exists (ID: `{ps_id}`)")
    else:
        # Resolve label IDs and site labels
        resolved_label_ids = [pg_label_ids[n] for n in ps_def.get("policy_group_labels", []) if n in pg_label_ids]
        body = {
            "name": ps_name,
            "description": ps_def.get("description", "").strip(),
            "state": ps_def.get("state", "MONITOR_ONLY"),
            "policyGroupLabels": resolved_label_ids,
            "siteLabels": ps_def.get("site_labels", []),
        }
        result = ccc_post(creds, token, "/api/policy/v1/policy-sets", body)
        ps_id = result.get("id", "unknown") if result else "unknown"
        actions.append(f"Policy set `{ps_name}`: **created** (ID: `{ps_id}`)")

    # ── 3. Security Profiles ─────────────────────────────────────
    sp_listing = ccc_get(creds, token, "/api/policy/v1/security-profiles") or {}
    sp_items = sp_listing.get("content", []) if isinstance(sp_listing, dict) else sp_listing
    sp_by_name = {sp["name"]: sp for sp in sp_items}

    sp_id_map: dict[str, str] = {}
    for sp in sp_defs:
        name = sp["name"]
        if name in sp_by_name:
            sp_id_map[name] = sp_by_name[name]["id"]
            actions.append(f"Security profile `{name}`: already exists")
        else:
            body = {
                "name": name,
                "description": sp.get("description", "").strip(),
                "ruleSet": build_rule_set(sp.get("rules", [])),
            }
            result = ccc_post(creds, token, "/api/policy/v1/security-profiles", body)
            sid = result.get("id", "unknown") if result else "unknown"
            sp_id_map[name] = sid
            actions.append(f"Security profile `{name}`: **created** (ID: `{sid}`)")

    # ── Report ───────────────────────────────────────────────────
    print("## Bootstrap — Forrester Demo")
    print()
    for line in actions:
        print(f"- {line}")
    print()
    print("### Resolved IDs (for inventory/group_vars/all.yml)")
    print("```yaml")
    print(f'ccc_policy_set_id:   "{ps_id}"')
    print(f'ccc_policy_set_name: "{ps_name}"')
    for label_name, label_id in pg_label_ids.items():
        print(f'ccc_pg_label_id:     "{label_id}"   # {label_name}')
    print("```")

    # Write structured output so the workflow can inject IDs into all.yml
    # without re-parsing markdown. Consumed by .github/workflows/bootstrap.yml.
    primary_label_name = next(iter(pg_label_ids), "")
    primary_label_id = pg_label_ids.get(primary_label_name, "")
    Path("/tmp/bootstrap-ids.json").write_text(json.dumps({
        "ccc_policy_set_id": ps_id,
        "ccc_policy_set_name": ps_name,
        "ccc_pg_label_id": primary_label_id,
        "ccc_pg_label_name": primary_label_name,
        "pg_label_ids": pg_label_ids,
        "sp_ids": sp_id_map,
    }, indent=2))

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as e:
        sys.stderr.write(f"CCC call failed: {e.stderr}\n")
        sys.exit(2)
