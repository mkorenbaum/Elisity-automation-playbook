#!/bin/bash
# The thinnest possible Elisity client — pure curl, no Python, no Ansible.
# Demonstrates that nothing in the integration is tooling-specific.
#
# Usage:  ./curl-one-liner.sh
# Env:    CCC_URL, CCC_CLIENT_ID, CCC_CLIENT_SECRET
set -euo pipefail

: "${CCC_URL:?set CCC_URL}"
: "${CCC_CLIENT_ID:?set CCC_CLIENT_ID}"
: "${CCC_CLIENT_SECRET:?set CCC_CLIENT_SECRET}"

CCC_BASE="${CCC_URL%/}"

# 1. Get a bearer token
TOKEN=$(curl -sk -X POST "${CCC_BASE}/auth/realms/elisity/protocol/openid-connect/token" \
  --data-urlencode "grant_type=client_credentials" \
  --data-urlencode "client_id=${CCC_CLIENT_ID}" \
  --data-urlencode "client_secret=${CCC_CLIENT_SECRET}" \
  --data-urlencode "scope=openid" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')

echo "Token acquired (${#TOKEN} chars)"

# 2. List the connectors — proves the API is reachable
curl -sk "${CCC_BASE}/api/identity-graph/v1/connector-connectivity" \
  -H "Authorization: Bearer ${TOKEN}" \
  | python3 -m json.tool | head -40

echo
echo "(See the Ansible / Terraform paths for the full demo flow —"
echo " this file just shows that you don't need either to drive Elisity.)"
