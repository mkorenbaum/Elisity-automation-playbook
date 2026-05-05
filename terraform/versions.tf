terraform {
  required_version = ">= 1.5.0"
  required_providers {
    restapi = {
      source  = "Mastercard/restapi"
      version = "~> 1.19"
    }
    external = {
      source  = "hashicorp/external"
      version = "~> 2.3"
    }
  }
}
