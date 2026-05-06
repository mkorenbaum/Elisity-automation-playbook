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
    skipped: list[str] = []

    for sp in profiles:
        name = sp["name"]
        if name in existing_by_name:
            skipped.append(name)
            continue

        body = {
            "name": name,
            "description": sp.get("description", "").strip(),
            "ruleSet": build_rule_set(sp.get("rules", [])),
        }
        ccc_post(creds, token, "/api/policy/v1/security-profiles", body)
        created.append(name)

    print("## Security Profiles")
    print()
    print(f"- Created: **{len(created)}**")
    print(f"- Already exist: **{len(skipped)}**")
    if created:
        print("\n### Created")
        for n in created:
            print(f"- `{n}`")
    if skipped:
        print("\n### Skipped (already exist)")
        for n in skipped:
            print(f"- `{n}`")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as e:
        sys.stderr.write(f"CCC call failed: {e.stderr}\n")
        sys.exit(2)
