################################################################################
# OAuth2 client_credentials flow → access token.
#
# Implementation: shell out to ../bin/ccc.py — the same Python stdlib helper
# the Ansible playbook uses. This avoids re-implementing OAuth in Terraform
# and keeps the auth surface identical across IaC tools.
################################################################################

data "external" "ccc_token" {
  program = [
    "bash", "-c",
    <<-EOT
      set -e
      TOKEN=$(printf '%s' "$CCC_CLIENT_SECRET" | python3 ../bin/ccc.py token \
        "$CCC_URL/auth/realms/elisity/protocol/openid-connect/token" \
        "$CCC_CLIENT_ID" -)
      printf '{"token":"%s"}\n' "$TOKEN"
    EOT
  ]

  query = {
    CCC_URL           = var.ccc_url
    CCC_CLIENT_ID     = var.ccc_client_id
    CCC_CLIENT_SECRET = var.ccc_client_secret
  }
}

################################################################################
# REST API provider — every CRUD on Elisity goes through this provider.
################################################################################

provider "restapi" {
  uri                  = var.ccc_url
  insecure             = true
  write_returns_object = true
  headers = {
    "Authorization" = "Bearer ${data.external.ccc_token.result.token}"
    "Content-Type"  = "application/json"
    "Accept"        = "application/json"
  }
  create_method  = "POST"
  update_method  = "PUT"
  destroy_method = "DELETE"
}
