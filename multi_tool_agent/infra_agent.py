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
# Vertex AI/Gemini configuration for summarization
GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL_NAME", "gemini-1.5-flash-latest")
VERTEX_AI_LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")

# --- Infrastructure Agent Tools ---

def run_terraform_plan(
    new_service_name: str,
    deployment_image_uri: str,
    region: str = "us-central1"
) -> dict:
    """
    Runs 'terraform plan' via a Cloud Build job to preview infrastructure changes.

    Args:
        new_service_name (str): The name for the new Cloud Run service to be planned.
        deployment_image_uri (str): The container image URI to use for the service.
        region (str): The GCP region for the deployment.

    Returns:
        dict: A dictionary containing the status and the raw Terraform plan output.
    """
    logging.info(f"Infra Agent: Running 'terraform plan' for new service '{new_service_name}'.")
    client = cloudbuild_v1.CloudBuildClient()
    
    # The build configuration points to the terraform/cloudbuild-terraform.yaml file
    # and passes Terraform variables as build-time substitution variables.
    build = cloudbuild_v1.Build(
        source={"repo_source": {"repo_name": "gemini-flow", "branch_name": "main"}},
        steps=[
            {
                "name": "hashicorp/terraform:1.8",
                "entrypoint": "terraform",
                "args": ["init"],
                "dir": "terraform",
            },
            {
                "name": "hashicorp/terraform:1.8",
                "entrypoint": "terraform",
                "args": [
                    "plan",
                    f"-var=project_id={GCP_PROJECT_ID}",
                    f"-var=region={region}",
                    f"-var=service_name={new_service_name}",
                    f"-var=image_uri={deployment_image_uri}",
                    "-no-color", # Ensures clean output for parsing
                ],
                "dir": "terraform",
            },
        ],
        timeout={"seconds": 1200},
    )

    try:
        operation = client.create_build(project_id=GCP_PROJECT_ID, build=build)
        result = operation.result()

        # It's tricky to get the stdout of a build step directly from the result object.
        # A more robust solution would save the plan to GCS and have this tool read it back.
        # For the hackathon, we'll return a success message and rely on checking the build logs manually for the plan.
        log_url = result.log_url
        logging.info(f"Infra Agent: 'terraform plan' build completed. Status: {result.status}. Logs at: {log_url}")

        if result.status == cloudbuild_v1.Build.Status.SUCCESS:
            # In a real app, you would parse the logs to get the plan output.
            # For now, we'll return a generic success message and the log URL.
            plan_summary = f"Terraform plan executed successfully. Please review the plan in the build logs before applying. Logs: {log_url}"
            return {"status": "SUCCESS", "plan_summary": plan_summary}
        else:
            return {"status": "FAILURE", "error_message": f"Terraform plan build failed. Check logs for details: {log_url}"}
            
    except Exception as e:
        error_msg = f"Infra Agent: Failed to submit 'terraform plan' build: {e}"
        logging.exception(error_msg)
        return {"status": "ERROR", "error_message": error_msg}


def run_terraform_apply(
    new_service_name: str,
    deployment_image_uri: str,
    region: str = "us-central1"
) -> dict:
    """
    Runs 'terraform apply' via a Cloud Build job to provision the infrastructure.

    Args:
        new_service_name (str): The name for the new Cloud Run service to create.
        deployment_image_uri (str): The container image URI to use for the service.
        region (str): The GCP region for the deployment.

    Returns:
        dict: A dictionary containing the status and result of the apply operation.
    """
    logging.info(f"Infra Agent: Running 'terraform apply' for new service '{new_service_name}'.")
    client = cloudbuild_v1.CloudBuildClient()

    build = cloudbuild_v1.Build(
        source={"repo_source": {"repo_name": "gemini-flow", "branch_name": "main"}},
        steps=[
            {
                "name": "hashicorp/terraform:1.8",
                "entrypoint": "terraform",
                "args": ["init"],
                "dir": "terraform",
            },
            {
                "name": "hashicorp/terraform:1.8",
                "entrypoint": "terraform",
                "args": [
                    "apply",
                    "-auto-approve",
                    f"-var=project_id={GCP_PROJECT_ID}",
                    f"-var=region={region}",
                    f"-var=service_name={new_service_name}",
                    f"-var=image_uri={deployment_image_uri}",
                ],
                "dir": "terraform",
            },
        ],
        timeout={"seconds": 1200},
    )

    try:
        operation = client.create_build(project_id=GCP_PROJECT_ID, build=build)
        result = operation.result()
        log_url = result.log_url
        logging.info(f"Infra Agent: 'terraform apply' build completed. Status: {result.status}. Logs at: {log_url}")
        
        if result.status == cloudbuild_v1.Build.Status.SUCCESS:
            # Here you would ideally parse the log for the output variable "service_url".
            return {"status": "SUCCESS", "message": f"Terraform apply completed successfully. Check build logs for outputs: {log_url}"}
        else:
            return {"status": "FAILURE", "error_message": f"Terraform apply build failed. Check logs for details: {log_url}"}

    except Exception as e:
        error_msg = f"Infra Agent: Failed to submit 'terraform apply' build: {e}"
        logging.exception(error_msg)
        return {"status": "ERROR", "error_message": error_msg}


# --- ADK Agent Definition ---
infra_agent = LlmAgent(
    name="geminiflow_infrastructure_agent",
    model=GEMINI_MODEL_NAME,
    description="An agent that can provision new cloud environments and services using Terraform.",
    instruction="You are an Infrastructure Agent. Your job is to plan and apply infrastructure changes using Terraform based on user requests.",
    tools=[
        run_terraform_plan,
        run_terraform_apply,
    ],
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

