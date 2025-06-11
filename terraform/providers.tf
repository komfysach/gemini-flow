# ------------------------------------------------------------------
# File: terraform/providers.tf
# Description: Configures the Google Cloud provider for Terraform.
# ------------------------------------------------------------------

terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

# Configure the Google Cloud provider with the project and region.
# These will be passed in as variables when Cloud Build runs Terraform.
provider "google" {
  project = var.project_id
  region  = var.region
}
