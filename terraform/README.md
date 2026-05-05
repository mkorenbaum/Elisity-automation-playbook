# Terraform mirror

The same Policy Group + Policy that the Ansible playbook creates,
expressed as a Terraform configuration. Same REST API, same target
tenant, same result.

This exists to demonstrate that Elisity's open API is tooling-agnostic —
nothing in the integration is Ansible-specific. Pick the IaC tool your
team already runs.

## Run it

```bash
cd terraform/

# Render terraform.tfvars from your CCC creds
cat > terraform.tfvars <<EOF
ccc_url           = "https://insights-demo.idp01.elisity.io"
ccc_client_id     = "your-client-id"
ccc_client_secret = "your-client-secret"
EOF

terraform init
terraform plan       # see what would change
terraform apply      # create the same demo PG + Policy
terraform destroy    # tear down
```

## What's in here

| File | Purpose |
|---|---|
| `versions.tf` | Provider pin (terraform 1.5+, http + restapi providers) |
| `variables.tf` | Inputs: CCC URL, client id, client secret + tenant-specific IDs |
| `auth.tf` | OAuth2 client_credentials → access token (uses local-exec calling bin/ccc.py) |
| `main.tf` | Policy Group + Policy resources via `restapi_object` |
| `outputs.tf` | Print the created object IDs |

## Notes

- This module uses [`Mastercard/restapi`](https://registry.terraform.io/providers/Mastercard/restapi)
  to drive Elisity's REST API directly. There is no native
  `elisity` provider yet — the same approach works against any of
  CCC's 436 endpoints.
- Auth happens via a `data.external` block that shells out to
  `../bin/ccc.py token`, so the OAuth flow is identical to the Ansible
  path. No duplication.
- For a real production deployment you'd:
  - Replace the `data.external` shellout with a proper provider plugin
    (or use Terraform's `http` provider with `lifecycle.replace_triggered_by`).
  - Use a remote state backend (S3 / GCS / Terraform Cloud).
  - Manage the secret via Vault / AWS Secrets Manager / TFC variables.

## Why both Ansible AND Terraform in the same repo?

The Forrester Wave question asks about **integration breadth** with
provisioning tools. Showing the same operation in two different IaC
tools — both using the same underlying REST API and the same auth
helper — is the most concrete answer.

The same patterns work for Argo CD, Pulumi, Crossplane, and any other
declarative tool. See `examples/` for short snippets.
