SHELL := /bin/bash

.DEFAULT_GOAL := help
.PHONY: help check bootstrap policy-set security-profiles policy-groups \
        policies demo cleanup \
        ci-creds ci-bootstrap ci-preview ci-apply ci-promote ci-drift

help:  ## Show this help
	@awk 'BEGIN{FS=":.*##"} /^[a-zA-Z_-]+:.*##/ {printf "  \033[36m%-20s\033[0m %s\n",$$1,$$2}' $(MAKEFILE_LIST)

check:  ## Verify ansible + creds.yml are present
	@which ansible-playbook >/dev/null 2>&1 || (echo "Install ansible: brew install ansible"; exit 1)
	@test -f creds.yml || (echo "Missing creds.yml — copy creds.yml.example to creds.yml and fill in"; exit 1)
	@echo "OK — ansible-playbook $$(ansible-playbook --version | head -1)"

bootstrap: check  ## First-run: create PG label + policy set + security profiles
	@python3 bin/bootstrap.py

policy-set: check  ## Apply policy-set.yaml to CCC
	ansible-playbook playbooks/apply-policy-set.yml

security-profiles: check  ## Apply security-profiles.yaml to CCC
	ansible-playbook playbooks/apply-security-profiles.yml

policy-groups: check  ## Apply policy-groups.yaml to CCC
	ansible-playbook playbooks/apply-pgs.yml

policies: check  ## Apply policies.yaml to CCC
	ansible-playbook playbooks/apply-policies.yml

demo: check  ## Full apply — policy-set, security-profiles, PGs, policies (dependency order)
	@echo "==> [1/4] Applying Policy Set..."
	@ansible-playbook playbooks/apply-policy-set.yml
	@echo
	@echo "==> [2/4] Applying Security Profiles..."
	@ansible-playbook playbooks/apply-security-profiles.yml
	@echo
	@echo "==> [3/4] Applying Policy Groups..."
	@ansible-playbook playbooks/apply-pgs.yml
	@echo
	@echo "==> [4/4] Applying Policies..."
	@ansible-playbook playbooks/apply-policies.yml
	@echo
	@echo "Done. Switch to CCC UI to see the new objects."

cleanup: check  ## Delete everything created by the demo
	ansible-playbook playbooks/99-cleanup.yml

# ─────────── CI targets (used by .github/workflows/) ──────────────────
# These render creds.yml from CCC_URL / CCC_CLIENT_ID / CCC_CLIENT_SECRET
# environment variables, then run a workflow stage.

ci-creds:  ## Render creds.yml from CCC_URL/ID/SECRET env vars (CI only)
	@test -n "$$CCC_URL" || (echo "ERROR: CCC_URL env var not set"; exit 1)
	@test -n "$$CCC_CLIENT_ID" || (echo "ERROR: CCC_CLIENT_ID env var not set"; exit 1)
	@test -n "$$CCC_CLIENT_SECRET" || (echo "ERROR: CCC_CLIENT_SECRET env var not set"; exit 1)
	@printf 'ccc_url:           "%s"\nccc_client_id:     "%s"\nccc_client_secret: %s\n' \
	  "$$CCC_URL" "$$CCC_CLIENT_ID" "$$(printf %s "$$CCC_CLIENT_SECRET" | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read()))')" > creds.yml
	@chmod 600 creds.yml
	@echo "Wrote creds.yml from environment ($$CCC_URL)"

ci-bootstrap: ci-creds  ## Bootstrap the demo policy set + labels + security profiles
	@python3 bin/bootstrap.py

ci-preview: ci-creds  ## PR preview — diff PR YAML vs main
	@python3 bin/preview.py --base-ref "$${BASE_REF:-origin/main}" > /tmp/preview.md
	@cat /tmp/preview.md

ci-apply: demo  ## Apply current YAML to CCC (used by main-push workflow)

ci-promote: ci-creds  ## Flip MONITOR_ONLY → MONITOR_AND_ENFORCE for managed policies
	@python3 bin/promote.py

ci-drift: ci-creds  ## Compare CCC state to main YAML; non-zero exit on drift
	@python3 bin/drift.py > /tmp/drift.md
	@cat /tmp/drift.md
