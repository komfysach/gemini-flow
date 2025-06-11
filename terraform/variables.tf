# ------------------------------------------------------------------
# File: terraform/variables.tf
# Description: Defines the input variables for our reusable
#              infrastructure module.
# ------------------------------------------------------------------

variable "project_id" {
  description = "The GCP project ID to deploy resources into."
  type        = string
}

variable "region" {
  description = "The GCP region where resources will be deployed."
  type        = string
  default     = "us-central1"
}

variable "service_name" {
  description = "The name of the Cloud Run service to create."
  type        = string
}

variable "image_uri" {
  description = "The full URI of the container image to deploy."
  type        = string
}