#!/usr/bin/env python3
"""
apply_security_profiles.py — create or update security profiles from
security-profiles.yaml.

Maps YAML rule definitions to CCC's ruleSet[].property format:
  - protocol: tcp=6, udp=17, icmp=1, any=null
  - permit: true (action=permit) or false (action=deny)

Idempotent: existing profiles matched by name are skipped.
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

# CCC encodes "any" protocol as -1 (per Allow All / Deny All system SPs).
# Omitting the field defaults server-side to 0, which is rejected.
PROTOCOL_MAP = {"tcp": 6, "udp": 17, "icmp": 1, "any": -1}


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
    body_path = "/tmp/.apply-sp-body.json"
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
    """PUT for in-place SP updates. Endpoint:
    /api/policy/v1/security-profiles/{id} (verified 2026-05-07)."""
    base = creds["ccc_url"].rstrip("/")
    body_path = "/tmp/.apply-sp-put.json"
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
    return None


def _live_rule_signature(live_sp: dict) -> str:
    """Canonical (protocol, dst, permit) tuples from CCC's securityRules[] read shape."""
    rules = []
    for r in live_sp.get("securityRules", []) or []:
        dsts = r.get("destinationPorts") or [{}]
        first = dsts[0] if dsts else {}
        if first.get("any"):
            dst = "Any"
        else:
            start, end = first.get("start"), first.get("end")
            if start is not None and end is not None:
                dst = str(start) if start == end else f"{start}-{end}"
            else:
                dst = "Any"
        rules.append({
            "protocol": r.get("protocol"),
            "dst": dst,
            "permit": bool(r.get("action", True)),
        })
    return json.dumps(sorted(rules, key=lambda x: json.dumps(x, sort_keys=True)),
                      sort_keys=True)


def _declared_rule_signature(rule_set: list[dict]) -> str:
    """Canonical signature from the write-time ruleSet[].property shape."""
    rules = []
    for entry in rule_set or []:
        prop = entry.get("property", {}) or {}
        rules.append({
            "protocol": prop.get("protocol"),
            "dst": prop.get("destinationPorts", "Any"),
            "permit": bool(prop.get("permit", True)),
        })
    return json.dumps(sorted(rules, key=lambda x: json.dumps(x, sort_keys=True)),
                      sort_keys=True)


def build_rule_set(rules: list[dict]) -> list[dict]:
    """Convert YAML rules to CCC ruleSet format.

    CCC create-time shape per the Allow All / Deny All system profiles
    and CCC builder healthcare template:
      { "property": {
          "protocol": -1,                 // 6=tcp, 17=udp, 1=icmp, -1=any (NEVER omit)
          "sourcePorts": "Any",           // "Any" or "<port>" or "<lo>-<hi>" — REQUIRED
          "destinationPorts": "Any",      // same; multi-port becomes multiple rules
          "permit": true                  // true=allow, false=deny
      } }

    Comma-separated dst_ports (e.g. "104,11112,11113") become one
    ruleSet entry per port — CCC expects single ports/ranges per
    entry, not comma-lists.
    """
    result = []
    for rule in rules:
        proto_str = rule.get("protocol", "any").lower()
        proto_num = PROTOCOL_MAP.get(proto_str, -1)
        is_permit = rule.get("action", "permit").lower() == "permit"

        src = rule.get("src_ports", "any")
        src_str = "Any" if str(src).lower() == "any" else str(src)

        dst_raw = rule.get("dst_ports", "any")
        if str(dst_raw).lower() == "any":
            dst_list: list[str] = ["Any"]
        else:
            dst_list = [p.strip() for p in str(dst_raw).split(",") if p.strip()]

        for dst_str in dst_list:
            result.append({"property": {
                "protocol": proto_num,
                "sourcePorts": src_str,
                "destinationPorts": dst_str,
                "permit": is_permit,
            }})
    return result


def main() -> int:
    creds = load_creds()
    sp_doc = yaml.safe_load((REPO_ROOT / "security-profiles.yaml").read_text()) or {}
    profiles = sp_doc.get("security_profiles", [])

    if not profiles:
        print("## Security Profiles\n\n> _No profiles declared._")
        return 0

    token = get_token(creds)

    # Fetch existing SPs
    listing = ccc_get(creds, token, "/api/policy/v1/security-profiles") or {}
    existing_sps = listing.get("content", []) if isinstance(listing, dict) else listing
    existing_by_name = {sp["name"]: sp for sp in existing_sps}

    created: list[str] = []
    updated: list[str] = []
    skipped: list[str] = []

    for sp in profiles:
        name = sp["name"]
        rule_set = build_rule_set(sp.get("rules", []))
        body = {
            "name": name,
            "description": sp.get("description", "").strip(),
            "ruleSet": rule_set,
        }

        existing_sp = existing_by_name.get(name)
        if existing_sp is not None:
            # Idempotent UPDATE — when CCC drifted from YAML (e.g. an
            # operator manually edited the rule set in the UI), apply
            # PUTs the SP back to the declared shape.
            drift = (
                (existing_sp.get("description") or "").strip() != body["description"]
                or _live_rule_signature(existing_sp) != _declared_rule_signature(rule_set)
            )
            if not drift:
                skipped.append(name)
                continue
            ccc_put(
                creds, token,
                f"/api/policy/v1/security-profiles/{existing_sp['id']}",
                body,
            )
            updated.append(name)
            continue

        ccc_post(creds, token, "/api/policy/v1/security-profiles", body)
        created.append(name)

    print("## Security Profiles")
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
