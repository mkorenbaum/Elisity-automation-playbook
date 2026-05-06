#!/usr/bin/env python3
"""
cleanup_demo.py — full v2 teardown of every Forrester-demo CCC object.

Used by .github/workflows/cleanup.yml to reset the tenant to a clean
slate between demo runs. Discovers what to delete by querying CCC
directly (not by reading a stale `.state.json`).

Deletion order (matters — CCC enforces dependency rules):
  1. All non-reflection Policies inside the FRSTR-HOSPITAL policy set
     (CCC auto-deletes the reflection-Return pairs with their parents)
  2. PUT-clear scope on the policy set: empty siteLabels, retain the
     System PG label as a no-op placeholder (CCC rejects empty
     policyGroupLabels with 400 'At least one Policy Group Label is
     required' — gotcha G12)
  3. DELETE the policy set itself
  4. DELETE every PG that carries the FORRESTER-DEMO label
  5. DELETE every Security Profile whose name starts with FRSTR-
     (skip CCC-managed `<name> Return` reflection SPs — gotcha G11)
  6. DELETE the FORRESTER-DEMO PG label

Safety: this script ONLY targets objects that satisfy the demo's
explicit markers. Tenant content without the FORRESTER-DEMO label,
the FRSTR- name prefix, and outside the FRSTR-HOSPITAL policy set is
NEVER touched. CORK PGs / Default policy set / built-in SPs survive.

Usage:
  python3 bin/cleanup_demo.py
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

# v2 demo scoping markers (must match policy-set.yaml + reconcile.py)
DEMO_PG_LABEL = "FORRESTER-DEMO"
DEMO_POLICY_SET = "FRSTR-HOSPITAL"
SP_PREFIX = "FRSTR-"


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


def ccc_call(creds: dict, token: str, method: str, path: str,
             body: dict | None = None, accept: str = "200,204,400,404") -> tuple[int, str]:
    base = creds["ccc_url"].rstrip("/")
    args = ["python3", str(CCC_PY), "call", "--method", method,
            "--token", token, "--accept-status", accept]
    if body is not None:
        body_path = "/tmp/.cleanup-body.json"
        Path(body_path).write_text(json.dumps(body))
        args += ["--body-file", body_path]
    args.append(f"{base}{path}")
    proc = subprocess.run(args, text=True, capture_output=True, check=True)
    return (proc.returncode, proc.stdout)


def parse_listing(text: str) -> list[dict]:
    """Handle both v2 envelope and v1 NDJSON shapes."""
    if not text.strip():
        return []
    try:
        d = json.loads(text)
        if isinstance(d, dict) and "content" in d:
            return d["content"]
        if isinstance(d, list):
            return d
    except json.JSONDecodeError:
        pass
    return [json.loads(l) for l in text.split("\n") if l.strip()]


def find_label_id(creds: dict, token: str, name: str) -> str | None:
    _, out = ccc_call(creds, token, "GET", "/api/policy/v1/policy-group-label")
    for lb in parse_listing(out):
        if lb.get("name") == name:
            return lb["id"]
    return None


def main() -> int:
    creds = load_creds()
    token = get_token(creds)
    deleted: list[str] = []

    # ── 1+2+3. Policy Set teardown (policies → PUT-clear → delete) ────
    _, out = ccc_call(creds, token, "GET", "/api/policy/v1/policy-sets")
    ps = next((p for p in parse_listing(out) if p.get("name") == DEMO_POLICY_SET), None)

    if ps:
        ps_id = ps["id"]
        # Delete primary policies (reflection auto-deletes with parents)
        _, out = ccc_call(creds, token, "GET",
                          f"/api/policy/v1/policy-sets/{ps_id}/policies?size=1000")
        for p in parse_listing(out):
            if p.get("isReflection"):
                continue
            ccc_call(creds, token, "DELETE",
                     f"/api/policy/v1/policy-sets/{ps_id}/policies/{p['id']}")
            deleted.append(f"Policy   `{p['name']}`")

        # PUT-clear scope; retain the System PG label per gotcha G12
        system_label_id = find_label_id(creds, token, "System")
        if system_label_id:
            ccc_call(creds, token, "PUT",
                     f"/api/policy/v1/policy-sets/{ps_id}",
                     body={
                         "name": ps["name"],
                         "description": "",
                         "policyGroupLabels": [system_label_id],
                         "siteLabels": [],
                     })

        ccc_call(creds, token, "DELETE", f"/api/policy/v1/policy-sets/{ps_id}")
        deleted.append(f"PolicySet `{DEMO_POLICY_SET}`")

    # ── 4. Policy Groups labelled FORRESTER-DEMO ──────────────────────
    label_id_to_name: dict[str, str] = {}
    _, out = ccc_call(creds, token, "GET", "/api/policy/v1/policy-group-label")
    for lb in parse_listing(out):
        label_id_to_name[lb["id"]] = lb["name"]

    _, out = ccc_call(creds, token, "GET", "/api/policy/v2/policy-groups?size=500")
    pgs_data = json.loads(out) if out.strip().startswith("{") else {"content": parse_listing(out)}
    for pg in pgs_data.get("content", []):
        carries_demo_label = False
        for label in pg.get("labels", []) or []:
            if isinstance(label, dict):
                if label.get("name") == DEMO_PG_LABEL:
                    carries_demo_label = True
                    break
            elif isinstance(label, str):
                if label_id_to_name.get(label) == DEMO_PG_LABEL:
                    carries_demo_label = True
                    break
        if carries_demo_label:
            ccc_call(creds, token, "DELETE",
                     f"/api/policy/v2/policy-groups/{pg['id']}")
            deleted.append(f"PG       `{pg['name']}`")

    # ── 5. Security Profiles named FRSTR-* ────────────────────────────
    _, out = ccc_call(creds, token, "GET", "/api/policy/v1/security-profiles")
    for sp in parse_listing(out):
        name = sp.get("name", "")
        # Skip CCC-managed reflection SPs (gotcha G11)
        if sp.get("isReflection") or name.endswith(" Return"):
            continue
        if name.startswith(SP_PREFIX):
            ccc_call(creds, token, "DELETE",
                     f"/api/policy/v1/security-profiles/{sp['id']}")
            deleted.append(f"SP       `{name}`")

    # ── 6. PG label FORRESTER-DEMO ────────────────────────────────────
    label_id = find_label_id(creds, token, DEMO_PG_LABEL)
    if label_id:
        ccc_call(creds, token, "DELETE",
                 f"/api/policy/v1/policy-group-label/{label_id}")
        deleted.append(f"PGLabel  `{DEMO_PG_LABEL}`")

    # ── Report ────────────────────────────────────────────────────────
    print("## 🧹 Cleanup — Forrester demo teardown")
    print()
    print(f"**Scope:** PG label `{DEMO_PG_LABEL}` + name prefix `{SP_PREFIX}*` + policy set `{DEMO_POLICY_SET}`")
    print()
    if not deleted:
        print("> ✅ Nothing to delete. Tenant already clean of demo state.")
        return 0
    print(f"Deleted **{len(deleted)}** object(s):")
    print()
    for line in deleted:
        print(f"- {line}")
    print()
    print("All objects without the `FORRESTER-DEMO` label, the `FRSTR-` name prefix,")
    print("and outside the `FRSTR-HOSPITAL` policy set were left untouched.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as e:
        sys.stderr.write(f"CCC call failed: {e.stderr}\n")
        sys.exit(2)
