#!/usr/bin/env python3
"""
preview.py — diff a PR's YAML state against main for all 4 object types.

Run from CI on every PR. Outputs a markdown report to stdout.

Compares:
  1. policy-set.yaml      — policy set definition
  2. security-profiles.yaml — security profile rules
  3. policy-groups.yaml    — policy group conditions
  4. policies.yaml         — inter-PG policies

Uses git show to read the base ref version, then compares against the
working tree. Best-effort CCC enrichment if creds are available.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CCC_PY = REPO_ROOT / "bin" / "ccc.py"


def git_show(ref: str, path: str) -> str:
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


def diff_scalar(base_val: Any, pr_val: Any, label: str) -> list[str]:
    """Diff two scalar/dict values, return list of change strings."""
    if base_val == pr_val:
        return []
    if base_val is None:
        return [f"**Added** {label}"]
    if pr_val is None:
        return [f"**Removed** {label}"]
    return [f"**Changed** {label}"]


def render_diff_section(title: str, items: list, renderer) -> str:
    if not items:
        return f"### {title}\n_None._\n"
    lines = [f"### {title} ({len(items)})"]
    for item in items:
        lines.append(f"- {renderer(item)}")
    return "\n".join(lines) + "\n"


def render_pg(pg: dict) -> str:
    m = pg.get("match", {})
    n_blocks = len(m.get("condition_blocks", []))
    return (
        f"`{pg['name']}`  \n"
        f"&nbsp;&nbsp;Type: `{pg.get('type', 'DYNAMIC')}` | "
        f"SL-{pg.get('security_level', '?')} | "
        f"{n_blocks} condition block(s)"
    )


def render_sp(sp: dict) -> str:
    n_rules = len(sp.get("rules", []))
    return f"`{sp['name']}` ({n_rules} rule(s))"


def render_policy(p: dict) -> str:
    return (
        f"`{p['name']}`  \n"
        f"&nbsp;&nbsp;{p.get('source_pg', '?')} "
        f"{'<->' if p.get('direction') == 'BIDIRECTIONAL' else '->'} "
        f"{p.get('destination_pg', '?')} | "
        f"SP: `{p.get('security_profile', '?')}` | "
        f"`{p.get('state', 'MONITOR_ONLY')}`"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-ref", default="origin/main")
    args = parser.parse_args()

    # ── Load base (main) and PR versions of all 4 YAMLs ─────────
    base_ps = yaml.safe_load(git_show(args.base_ref, "policy-set.yaml") or "{}") or {}
    pr_ps = read_yaml_file(REPO_ROOT / "policy-set.yaml")

    base_sps = (yaml.safe_load(git_show(args.base_ref, "security-profiles.yaml") or "{}") or {}).get("security_profiles", [])
    pr_sps = read_yaml_file(REPO_ROOT / "security-profiles.yaml").get("security_profiles", [])

    base_pgs = (yaml.safe_load(git_show(args.base_ref, "policy-groups.yaml") or "{}") or {}).get("policy_groups", [])
    pr_pgs = read_yaml_file(REPO_ROOT / "policy-groups.yaml").get("policy_groups", [])

    base_pols = (yaml.safe_load(git_show(args.base_ref, "policies.yaml") or "{}") or {}).get("policies", [])
    pr_pols = read_yaml_file(REPO_ROOT / "policies.yaml").get("policies", [])

    # ── Diff each section ────────────────────────────────────────
    ps_changes = diff_scalar(base_ps.get("policy_set"), pr_ps.get("policy_set"), "policy set")
    sp_diff = diff_lists(base_sps, pr_sps)
    pg_diff = diff_lists(base_pgs, pr_pgs)
    pol_diff = diff_lists(base_pols, pr_pols)

    total = (
        len(ps_changes)
        + len(sp_diff["added"]) + len(sp_diff["removed"]) + len(sp_diff["changed"])
        + len(pg_diff["added"]) + len(pg_diff["removed"]) + len(pg_diff["changed"])
        + len(pol_diff["added"]) + len(pol_diff["removed"]) + len(pol_diff["changed"])
    )

    # ── Render report ────────────────────────────────────────────
    print("## PR Preview -- Elisity Microsegmentation (v2)")
    print()
    if total == 0:
        print("> No segmentation changes in this PR.")
        return 0

    print(f"> This PR proposes **{total} change(s)** across 4 declaration files.")
    print()
    print("**Pipeline:** PR review -> merge to `main` (auto-apply in `MONITOR_ONLY`) "
          "-> release tag (auto-promote to `MONITOR_AND_ENFORCE`).")
    print()

    # Policy Set
    if ps_changes:
        print("## Policy Set changes")
        for c in ps_changes:
            print(f"- {c}")
        print()

    # Security Profiles
    print("## Security Profile changes")
    print(render_diff_section("Added", sp_diff["added"], render_sp))
    print(render_diff_section("Removed", sp_diff["removed"], render_sp))
    print(render_diff_section("Changed", sp_diff["changed"],
                              lambda c: f"`{c['name']}` (rules differ)"))

    # Policy Groups
    print("## Policy Group changes")
    print(render_diff_section("Added", pg_diff["added"], render_pg))
    print(render_diff_section("Removed", pg_diff["removed"], render_pg))
    print(render_diff_section("Changed", pg_diff["changed"],
                              lambda c: f"`{c['name']}` (fields differ)"))

    # Policies
    print("## Policy changes")
    print(render_diff_section("Added", pol_diff["added"], render_policy))
    print(render_diff_section("Removed", pol_diff["removed"], render_policy))
    print(render_diff_section("Changed", pol_diff["changed"],
                              lambda c: f"`{c['name']}` (fields differ)"))

    print("---")
    print("- All new policies start in `MONITOR_ONLY` -- no enforcement until release.")
    print("- Drift between this repo and the live tenant is checked hourly.")
    print("- Source of truth: this repo. Production change = merge to `main`.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
