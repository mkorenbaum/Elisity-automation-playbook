SHELL := /bin/bash

.DEFAULT_GOAL := help
.PHONY: help check connectors policy-groups policies verify demo cleanup

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
