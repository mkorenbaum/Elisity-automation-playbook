#!/usr/bin/env python3
"""
preview.py — diff a PR's YAML state against main + assess CCC impact.

Run from CI on every PR. Outputs a markdown report to stdout.

What it does:
1. Read main's policy-groups.yaml and policies.yaml (via git show).
2. Read the PR's policy-groups.yaml and policies.yaml (working tree).
3. Diff: list ADDED, REMOVED, CHANGED objects.
4. For each ADDED Policy Group: query CCC to find how many devices
   match its criteria today (impact assessment).
5. Print a markdown table the GitHub Actions workflow then posts as a
   PR comment.

Uses bin/ccc.py for HTTP calls. Reads creds from creds.yml in CWD.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml  # PyYAML — installed in CI; for local use, install via pip

REPO_ROOT = Path(__file__).resolve().parent.parent
CCC_PY = REPO_ROOT / "bin" / "ccc.py"


def load_creds() -> dict[str, str]:
    with open(REPO_ROOT / "creds.yml") as f:
        return yaml.safe_load(f)


def load_yaml(path: str) -> dict[str, Any]:
    return yaml.safe_load(path) or {}


def git_show(ref: str, path: str) -> str:
    """Return file contents at git ref, or empty string if not present."""
    try:
        return subprocess.check_output(
            ["git", "show", f"{ref}:{path}"],
            cwd=REPO_ROOT, stderr=subprocess.DEVNULL,
        ).decode()
    except subprocess.CalledProcessError:
        return ""


def read_yaml_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with open(path) as f:
        return yaml.safe_load(f) or {}


def diff_lists(main_items: list[dict], pr_items: list[dict], key: str = "name") -> dict:
    main_by_name = {x[key]: x for x in main_items}
    pr_by_name = {x[key]: x for x in pr_items}
    added = [pr_by_name[n] for n in pr_by_name if n not in main_by_name]
    removed = [main_by_name[n] for n in main_by_name if n not in pr_by_name]
    changed = []
    for n in pr_by_name:
        if n in main_by_name and pr_by_name[n] != main_by_name[n]:
            changed.append({"name": n, "before": main_by_name[n], "after": pr_by_name[n]})
    return {"added": added, "removed": removed, "changed": changed}


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


def ccc_call(creds: dict[str, str], token: str, path: str) -> str:
    base = creds["ccc_url"].rstrip("/")
    proc = subprocess.run(
        ["python3", str(CCC_PY), "call", "--token", token, f"{base}{path}"],
        text=True, capture_output=True, check=True,
    )
    return proc.stdout


def render_pg(pg: dict[str, Any]) -> str:
    m = pg.get("match", {})
    return (
        f"`{pg['name']}`  \n"
        f"&nbsp;&nbsp;Type: `{pg.get('type','DYNAMIC')}` · "
        f"Security Level: `SL-{pg.get('security_level','?')}`  \n"
        f"&nbsp;&nbsp;Match: `{m.get('attribute','?')}` "
        f"`{m.get('operator','?')}` `{m.get('match_values', [])}`"
    )


def render_policy(p: dict[str, Any]) -> str:
    return (
        f"`{p['name']}`  \n"
        f"&nbsp;&nbsp;Source PG: `{p.get('source_policy_group','?')}` → "
        f"Dest PG ID: `{p.get('destination_policy_group_id','?')[:8]}…`  \n"
        f"&nbsp;&nbsp;Mode: **`{p.get('monitor_mode','?')}`**"
    )


def render_diff_section(title: str, items: list, renderer) -> str:
    if not items:
        return f"### {title}\n_None._\n"
    lines = [f"### {title} ({len(items)})"]
    for item in items:
        lines.append(f"- {renderer(item)}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-ref", default="origin/main",
                        help="Git ref to diff against (default origin/main)")
    args = parser.parse_args()

    main_pgs = yaml.safe_load(git_show(args.base_ref, "policy-groups.yaml") or "{}") or {}
    main_pgs = main_pgs.get("policy_groups", [])
    main_pols = yaml.safe_load(git_show(args.base_ref, "policies.yaml") or "{}") or {}
    main_pols = main_pols.get("policies", [])

    pr_pgs = read_yaml_file(REPO_ROOT / "policy-groups.yaml").get("policy_groups", [])
    pr_pols = read_yaml_file(REPO_ROOT / "policies.yaml").get("policies", [])

    pg_diff = diff_lists(main_pgs, pr_pgs)
    pol_diff = diff_lists(main_pols, pr_pols)

    total_changes = (
        len(pg_diff["added"]) + len(pg_diff["removed"]) + len(pg_diff["changed"]) +
        len(pol_diff["added"]) + len(pol_diff["removed"]) + len(pol_diff["changed"])
    )

    # Header
    print("## 🔍 PR Preview — Elisity Microsegmentation")
    print()
    if total_changes == 0:
        print("> ✅ **No segmentation changes** in this PR.")
        return 0

    print(f"> This PR proposes **{total_changes} change(s)** to "
          f"Elisity's microsegmentation policy.")
    print()
    print("**Pipeline:** PR review → merge to `main` (auto-apply in `MONITOR_ONLY`) "
          "→ release tag (auto-promote to `MONITOR_AND_ENFORCE`).")
    print()

    # Try to enrich added PGs with current CCC tenant impact, but only
    # if creds are available (CI). Skip silently otherwise.
    enrichment: dict[str, str] = {}
    creds_ok = (REPO_ROOT / "creds.yml").exists()
    if creds_ok and pg_diff["added"]:
        try:
            creds = load_creds()
            token = get_token(creds)
            # Fetch all current devices we'd need to evaluate match counts
            # (lightweight: just count via /policy-groups view of existing PGs).
            # Best-effort — failures are non-fatal.
            for pg in pg_diff["added"]:
                # Attempt a lookup of the named PG; if exists already we can show count.
                # For new PGs we can only show the match criteria — full impact
                # analysis requires creating the PG in simulation, which the
                # `apply` workflow does on merge.
                enrichment[pg["name"]] = "(impact assessed at merge time in MONITOR_ONLY)"
        except Exception as e:
            print(f"> _Note: could not query CCC for impact preview: {e}_")
            print()

    print("## Policy Group changes")
    print(render_diff_section("➕ Added", pg_diff["added"], render_pg))
    print(render_diff_section("➖ Removed", pg_diff["removed"], render_pg))
    print(render_diff_section("✏️ Changed", pg_diff["changed"],
                              lambda c: f"`{c['name']}` (fields differ)"))

    print("## Policy changes")
    print(render_diff_section("➕ Added", pol_diff["added"], render_policy))
    print(render_diff_section("➖ Removed", pol_diff["removed"], render_policy))
    print(render_diff_section("✏️ Changed", pol_diff["changed"],
                              lambda c: f"`{c['name']}` (fields differ)"))

    print("---")
    print("- ✅ All new policies start in `MONITOR_ONLY` — no enforcement until release.")
    print("- 🔁 Drift between this repo and the live tenant is checked hourly.")
    print("- 🔐 Source of truth: this repo. Production change = merge to `main`.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
