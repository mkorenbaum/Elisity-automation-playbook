variable "ccc_url" {
  description = "Elisity Cloud Control Center base URL (no trailing slash)"
  type        = string
}

variable "ccc_client_id" {
  description = "OAuth2 client_credentials client ID"
  type        = string
  sensitive   = true
}

variable "ccc_client_secret" {
  description = "OAuth2 client_credentials client secret"
  type        = string
  sensitive   = true
}

# Tenant-specific IDs used by the demo. These match the values in
# inventory/group_vars/all.yml so the Terraform module produces the same
# state as the Ansible playbook.

variable "ccc_dest_policy_group_id" {
  description = "Existing Policy Group ID used as the destination of the demo policy"
  type        = string
  default     = "316cc4fd-98f5-4f82-b7e8-58bd20a24353"  # "Unverified Servers Storage" on insights-demo
}

variable "ccc_policy_set_id" {
  description = "Policy Set the demo policy is created in"
  type        = string
  default     = "ea9e9ec2-cffc-433a-8b68-4ba5969a8be6"  # "Default" on insights-demo
}

variable "ccc_security_profile_id" {
  description = "Security Profile applied to the demo policy"
  type        = string
  default     = "97e9e16d-8a9d-41a1-9b3b-5fb92165b08e"  # "Allow All" on insights-demo
}

variable "ccc_default_label_id" {
  description = "Policy Group label (required on every PG create)"
  type        = string
  default     = "1776091f-81a0-4382-aa7b-8be7284e6397"
}

variable "demo_pg_name" {
  description = "Name of the demo Policy Group"
  type        = string
  default     = "forrester-demo-imaging-tf"
}

variable "monitor_mode" {
  description = "Policy mode: MONITOR_ONLY (simulation) or MONITOR_AND_ENFORCE"
  type        = string
  default     = "MONITOR_ONLY"
  validation {
    condition     = contains(["MONITOR_ONLY", "MONITOR_AND_ENFORCE", "MONITOR_EXTERNAL"], var.monitor_mode)
    error_message = "monitor_mode must be MONITOR_ONLY, MONITOR_AND_ENFORCE, or MONITOR_EXTERNAL."
  }
}
