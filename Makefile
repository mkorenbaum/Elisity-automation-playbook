SHELL := /bin/bash

.DEFAULT_GOAL := help
.PHONY: help check connectors policy-groups policies verify demo cleanup \
        ci-creds ci-preview ci-apply ci-promote ci-drift

help:  ## Show this help
	@awk 'BEGIN{FS=":.*##"} /^[a-zA-Z_-]+:.*##/ {printf "  \033[36m%-16s\033[0m %s\n",$$1,$$2}' $(MAKEFILE_LIST)

check:  ## Verify ansible + creds.yml are present
	@which ansible-playbook >/dev/null 2>&1 || (echo "Install ansible: brew install ansible"; exit 1)
	@test -f creds.yml || (echo "Missing creds.yml — copy creds.yml.example to creds.yml and fill in"; exit 1)
	@echo "OK — ansible-playbook $$(ansible-playbook --version | head -1)"

connectors: check  ## Read-only: list connectors via the CCC API
	ansible-playbook playbooks/00-list-connectors.yml

policy-groups: check  ## Apply policy-groups.yaml to CCC
	ansible-playbook playbooks/01-policy-groups.yml

policies: check  ## Apply policies.yaml to CCC
	ansible-playbook playbooks/02-policies.yml

verify: check  ## Re-fetch and print created objects
	ansible-playbook playbooks/03-verify.yml

demo: check  ## Full demo — list connectors, apply PGs, apply policies, verify
	@echo "==> [1/4] Listing connectors via CCC REST API..."
	@ansible-playbook playbooks/00-list-connectors.yml
	@echo
	@echo "==> [2/4] Applying Policy Groups from policy-groups.yaml..."
	@ansible-playbook playbooks/01-policy-groups.yml
	@echo
	@echo "==> [3/4] Applying Policies from policies.yaml..."
	@ansible-playbook playbooks/02-policies.yml
	@echo
	@echo "==> [4/4] Verifying created objects..."
	@ansible-playbook playbooks/03-verify.yml
	@echo
	@echo "Done. Switch to CCC UI → Policy Groups and Policies to see the new objects."

cleanup: check  ## Delete everything created by `demo`
	ansible-playbook playbooks/99-cleanup.yml

# ─────────── CI targets (used by .github/workflows/) ──────────────────
# These render creds.yml from CCC_URL / CCC_CLIENT_ID / CCC_CLIENT_SECRET
# environment variables, then run a workflow stage. The Makefile is the
# single contract — workflows only call `make ci-*` targets, so the
# Ansible plumbing stays in one place.

ci-creds:  ## Render creds.yml from CCC_URL/ID/SECRET env vars (CI only)
	@test -n "$$CCC_URL" || (echo "ERROR: CCC_URL env var not set"; exit 1)
	@test -n "$$CCC_CLIENT_ID" || (echo "ERROR: CCC_CLIENT_ID env var not set"; exit 1)
	@test -n "$$CCC_CLIENT_SECRET" || (echo "ERROR: CCC_CLIENT_SECRET env var not set"; exit 1)
	@printf 'ccc_url:           "%s"\nccc_client_id:     "%s"\nccc_client_secret: %s\n' \
	  "$$CCC_URL" "$$CCC_CLIENT_ID" "$$(printf %s "$$CCC_CLIENT_SECRET" | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read()))')" > creds.yml
	@chmod 600 creds.yml
	@echo "Wrote creds.yml from environment ($$CCC_URL)"

ci-preview: ci-creds  ## PR preview — diff PR YAML vs main + CCC impact
	@python3 bin/preview.py --base-ref "$${BASE_REF:-origin/main}" > /tmp/preview.md
	@cat /tmp/preview.md

ci-apply: demo  ## Apply current YAML to CCC (used by main-push workflow)

ci-promote: ci-creds  ## Flip MONITOR_ONLY → MONITOR_AND_ENFORCE for managed policies
	@python3 bin/promote.py

ci-drift: ci-creds  ## Compare CCC state to main YAML; non-zero exit on drift
	@python3 bin/drift.py > /tmp/drift.md
	@cat /tmp/drift.md
