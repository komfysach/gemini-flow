# ------------------------------------------------------------------
# File: terraform/backend.tf
# Description: Configures the GCS backend to securely store the
#              Terraform state file.
# ------------------------------------------------------------------

terraform {
  backend "gcs" {
    bucket = "geminiflow-461207-tfstate"
    prefix = "terraform/state"
  }
}