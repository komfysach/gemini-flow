# ------------------------------------------------------------------
# File: terraform/main.tf
# Description: Defines the actual Google Cloud resources to be
#              created by Terraform (a Cloud Run service).
# ------------------------------------------------------------------

# Create the Cloud Run v2 service
resource "google_cloud_run_v2_service" "main_service" {
  name     = var.service_name
  location = var.region
  project  = var.project_id

  template {
    containers {
      image = var.image_uri
      ports {
        container_port = 8080 # Assuming the Go app's por
      }
    }
  }

  # Optional: Define traffic split to send 100% to the latest revision
  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }
}

# Make the Cloud Run service publicly accessible
resource "google_cloud_run_v2_service_iam_member" "public_access" {
  project  = google_cloud_run_v2_service.main_service.project
  location = google_cloud_run_v2_service.main_service.location
  name     = google_cloud_run_v2_service.main_service.name
  
  role   = "roles/run.invoker"
  member = "allUsers"

  # Depends on the service being created first
  depends_on = [google_cloud_run_v2_service.main_service]
}

# Output the URL of the deployed service
output "service_url" {
  description = "The URL of the deployed Cloud Run service."
  value       = google_cloud_run_v2_service.main_service.uri
}
