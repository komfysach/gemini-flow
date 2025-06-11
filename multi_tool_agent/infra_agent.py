# infra_agent.py
# Agent Development Kit (ADK) Infrastructure Provisioning Agent for GeminiFlow

import os
import time
import logging
from google.adk.agents import LlmAgent
from google.cloud.devtools import cloudbuild_v1
import google.generativeai as genai
from dotenv import load_dotenv
load_dotenv()

# Configure basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Infrastructure Agent Configuration ---
# For local testing, ensure GOOGLE_APPLICATION_CREDENTIALS is set to the path of
# the geminiflow-infra-sa@... service account key file.
# This SA needs "Cloud Build Editor" and permissions to create the resources in main.tf.
GCP_PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT")
# The service account that will EXECUTE the Terraform steps inside Cloud Build.
# It needs permissions to create Cloud Run services, manage GCS state, etc.
# Example: geminiflow-infra-sa@geminiflow-461207.iam.gserviceaccount.com
TERRAFORM_EXECUTION_SA = os.getenv("TERRAFORM_SERVICE_ACCOUNT")
# The name of the GitHub repository connected to Cloud Build where your terraform/ directory lives.
TERRAFORM_SOURCE_REPO_NAME = os.getenv("TERRAFORM_SOURCE_REPO", "gemini-flow")
TERRAFORM_TRIGGER_ID = os.getenv("TERRAFORM_TRIGGER_ID", "terraform-plan-and-apply")
# Vertex AI/Gemini configuration for summarization
GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL_NAME", "gemini-1.5-flash-latest")
VERTEX_AI_LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")

# --- Infrastructure Agent Tools ---

def _run_terraform_trigger(command: str, new_service_name: str, deployment_image_uri: str, region: str) -> dict:
    """Helper function to run the Terraform trigger in Cloud Build with 'plan' or 'apply'."""
    logging.info(f"Infra Agent: Invoking Terraform trigger for command '{command}' on service '{new_service_name}'.")
    client = cloudbuild_v1.CloudBuildClient()

    # The source to build. We specify the branch and substitutions here to override
    # any defaults in the trigger, ensuring we build the right thing every time.
    source = cloudbuild_v1.types.RepoSource(
        repo_name=TERRAFORM_SOURCE_REPO_NAME,
        branch_name="main", # Or your default branch for terraform files
        substitutions={
            "_COMMAND": command,
            "_REGION": region,
            "_SERVICE_NAME": new_service_name,
            "_IMAGE_URI": deployment_image_uri,
        },
    )
    
    try:
        operation = client.run_build_trigger(
            project_id=GCP_PROJECT_ID,
            trigger_id=TERRAFORM_TRIGGER_ID,
            source=source
        )
        result = operation.result()
        log_url = result.log_url
        logging.info(f"Infra Agent: Terraform trigger run completed. Status: {result.status}. Logs at: {log_url}")

        if result.status == cloudbuild_v1.Build.Status.SUCCESS:
            # For a real implementation, you would parse the logs to get the plan/apply output.
            # This simplified version just confirms success.
            return {"status": "SUCCESS", "message": f"Terraform {command} completed successfully. See logs for details.", "log_url": log_url}
        else:
            return {"status": "FAILURE", "error_message": f"Terraform {command} build failed. Check logs for details: {log_url}"}

    except Exception as e:
        error_msg = f"Infra Agent: Failed to run Terraform trigger: {e}"
        logging.exception(error_msg)
        return {"status": "ERROR", "error_message": error_msg}


def run_terraform_plan(
    new_service_name: str,
    deployment_image_uri: str,
    region: str = "us-central1"
) -> dict:
    """Runs 'terraform plan' via a Cloud Build trigger to preview infrastructure changes."""
    return _run_terraform_trigger(
        command="plan",
        new_service_name=new_service_name,
        deployment_image_uri=deployment_image_uri,
        region=region
    )

def run_terraform_apply(
    new_service_name: str,
    deployment_image_uri: str,
    region: str = "us-central1"
) -> dict:
    """Runs 'terraform apply' via a Cloud Build trigger to provision the infrastructure."""
    return _run_terraform_trigger(
        command="apply -auto-approve",
        new_service_name=new_service_name,
        deployment_image_uri=deployment_image_uri,
        region=region
    )

# --- Local Testing Example ---
if __name__ == "__main__":
    # Before running:
    # 1. Install libraries: `pip install google-cloud-build`
    # 2. Set GOOGLE_APPLICATION_CREDENTIALS to your Infra SA key file.
    # 3. Set GOOGLE_CLOUD_PROJECT.
    # 4. CRITICAL: Replace the placeholder below with a REAL image URI to deploy.
    
    if not GCP_PROJECT_ID:
         print("Error: Please set GOOGLE_CLOUD_PROJECT environment variable.")
    else:
        # IMPORTANT: Find an image in your Artifact Registry from a previous BTA run.
        test_image_for_new_service = "us-central1-docker.pkg.dev/geminiflow-461207/gemini-flow-apps/gemini-flow-hello-world:latest" # REPLACE if needed
        new_service_name = f"staging-service-{int(time.time())}" # Create a unique name

        print(f"--- Testing Infrastructure Agent Tools for new service: {new_service_name} ---")
        
        # Step 1: Run Terraform Plan
        plan_report = run_terraform_plan(
            new_service_name=new_service_name,
            deployment_image_uri=test_image_for_new_service
        )
        print("\n--- Terraform Plan Report ---")
        print(plan_report)

        # Step 2: (Simulated Human Approval) Apply the plan
        if plan_report.get("status") == "SUCCESS":
            print("\n--- Plan successful. Simulating human approval and running apply... ---")
            apply_report = run_terraform_apply(
                new_service_name=new_service_name,
                deployment_image_uri=test_image_for_new_service
            )
            print("\n--- Terraform Apply Report ---")
            print(apply_report)
        else:
            print("\nSkipping apply due to plan failure or error.")

