################################################################################
# Demo: a Dynamic Policy Group + a Policy referencing it. Same shape as the
# Ansible playbook's policy-groups.yaml + policies.yaml.
#
# When you `terraform apply`:
#   1. POST /api/policy/v2/policy-groups/dynamic   → creates the PG
#   2. POST /api/policy/v1/policy-sets/{ps}/policies → creates the policy
#
# When you `terraform destroy`:
#   1. DELETE the policy
#   2. DELETE the PG
#
# Same REST API the Ansible playbook drives. Same tenant. Different IaC tool.
################################################################################

resource "restapi_object" "demo_policy_group" {
  path = "/api/policy/v2/policy-groups/dynamic"

  data = jsonencode({
    name              = var.demo_pg_name
    description       = "Imaging workstations classified by hostname pattern. Created via Terraform — same REST API as the Ansible playbook."
    policyGroupType   = "DYNAMIC"
    securityLevel     = 3
    autoLockDevices   = false
    labels            = [var.ccc_default_label_id]
    matchingCriteria  = {
      conditionBlocks = [{
        conditions = [{
          operator      = "CONTAINS"
          attributeFqdn = "core.hostname"
          attributeType = "STRING"
          value         = ["IMAGING"]
        }]
      }]
    }
  })

  # The CCC create endpoint returns just the UUID as a quoted string,
  # not a JSON object. The Mastercard/restapi provider extracts that.
  id_attribute = "id"
}

resource "restapi_object" "demo_policy" {
  path = "/api/policy/v1/policy-sets/${var.ccc_policy_set_id}/policies"

  data = jsonencode({
    name             = "${var.demo_pg_name} > Unverified Servers Storage"
    description      = "Allow imaging workstations to talk to the destination group. Created via Terraform in MONITOR_ONLY."
    srcPolicyGroup   = restapi_object.demo_policy_group.id
    dstPolicyGroup   = var.ccc_dest_policy_group_id
    securityProfiles = [var.ccc_security_profile_id]
    finalAction      = var.ccc_security_profile_id
    monitorMode      = var.monitor_mode
    isMirrored       = false
    isCustomName     = false
  })

  id_attribute = "id"

  depends_on = [restapi_object.demo_policy_group]
}
