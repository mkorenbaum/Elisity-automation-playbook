output "policy_group_id" {
  description = "UUID of the Policy Group created in CCC"
  value       = restapi_object.demo_policy_group.id
}

output "policy_id" {
  description = "UUID of the Policy created in CCC"
  value       = restapi_object.demo_policy.id
}

output "ccc_ui_link" {
  description = "Open the demo Policy Group in the CCC UI"
  value       = "${var.ccc_url}/policy-groups/${restapi_object.demo_policy_group.id}"
}
