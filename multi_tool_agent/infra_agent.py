# infra_agent.py
# Agent Development Kit (ADK) Infrastructure Provisioning Agent for GeminiFlow

import os
import re
import logging
import time
from google.adk.agents import LlmAgent
from google.cloud.devtools import cloudbuild_v1
from google.cloud import storage
from dotenv import load_dotenv
load_dotenv()

# Configure basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Infrastructure Agent Configuration ---
GCP_PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT")
TERRAFORM_SERVICE_ACCOUNT = os.getenv("TERRAFORM_SERVICE_ACCOUNT")
TERRAFORM_SOURCE_REPO = os.getenv("TERRAFORM_SOURCE_REPO", "gemini-flow")
TERRAFORM_TRIGGER_ID = os.getenv("TERRAFORM_TRIGGER_ID", "terraform-plan-and-apply")
TERRAFORM_LOGS_BUCKET = os.getenv("TERRAFORM_LOGS_BUCKET", "gemini-flow-build-artifacts")
GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL_NAME", "gemini-2.0-flash-exp")
VERTEX_AI_LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")

# Configure Gemini properly - use either Vertex AI or direct API
gemini_client = None
if os.getenv("GEMINI_API_KEY"):
    try:
        import google.generativeai as genai
        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
        gemini_client = genai
        logging.info(f"Infra Agent: Gemini client configured with API key.")
    except Exception as e_genai:
        logging.warning(f"Infra Agent: Could not configure Gemini with API key: {e_genai}")
elif GCP_PROJECT_ID and VERTEX_AI_LOCATION:
    try:
        import vertexai
        from vertexai.generative_models import GenerativeModel
        vertexai.init(project=GCP_PROJECT_ID, location=VERTEX_AI_LOCATION)
        gemini_client = "vertex"
        logging.info(f"Infra Agent: Vertex AI client configured.")
    except Exception as e_vertex:
        logging.warning(f"Infra Agent: Could not configure Vertex AI client: {e_vertex}")
else:
    logging.warning("Infra Agent: Neither GEMINI_API_KEY nor GCP credentials configured. Summarization disabled.")

# --- Infrastructure Agent Tools ---

def _save_log_archive(log_content: str, build_id: str, command: str) -> None:
    """Saves a copy of the log content to the designated TERRAFORM_LOGS_BUCKET for archival."""
    if not TERRAFORM_LOGS_BUCKET:
        logging.warning("Infra Agent: TERRAFORM_LOGS_BUCKET not set. Skipping log archival.")
        return
    try:
        storage_client = storage.Client(project=GCP_PROJECT_ID)
        bucket = storage_client.bucket(TERRAFORM_LOGS_BUCKET)
        object_name = f"terraform-logs/{command}/{build_id}/terraform_log.txt"
        blob = bucket.blob(object_name)
        blob.upload_from_string(log_content)
        logging.info(f"Infra Agent: Saved log archive to gs://{TERRAFORM_LOGS_BUCKET}/{object_name}")
    except Exception as e:
        logging.error(f"Infra Agent: Failed to save log archive to TERRAFORM_LOGS_BUCKET: {e}")

def _get_build_logs(build_result) -> str | None:
    """
    Directly retrieves logs from the build's GCS bucket.
    Includes a retry mechanism to wait for the log file to become available.
    """
    build_id = build_result.id
    # The build result contains the path to the bucket where logs are stored.
    logs_bucket_path = build_result.logs_bucket

    if not logs_bucket_path or not logs_bucket_path.startswith('gs://'):
        logging.error(f"Infra Agent: Build {build_id} did not provide a valid GCS logs_bucket path.")
        return None

    try:
        # Extract bucket name from 'gs://<bucket_name>/...'
        bucket_name = logs_bucket_path.split('gs://')[1].split('/')[0]
        # The log file is consistently named log-{build_id}.txt at the root of the log path.
        log_file_name = f"log-{build_id}.txt"
        
        storage_client = storage.Client(project=GCP_PROJECT_ID)
        source_bucket = storage_client.bucket(bucket_name)
        source_blob = source_bucket.blob(log_file_name)

        log_content = None
        # Retry logic: It can take a few moments for the log file to appear after the build completes.
        for attempt in range(6): # Try for up to 60 seconds
            if source_blob.exists():
                logging.info(f"Infra Agent: Found log file at gs://{bucket_name}/{log_file_name}.")
                log_content = source_blob.download_as_text()
                break
            logging.info(f"Infra Agent: Log not yet available at gs://{bucket_name}/{log_file_name}. Waiting 10s... (Attempt {attempt+1}/6)")
            time.sleep(10)
        
        return log_content

    except Exception as e:
        logging.error(f"Infra Agent: An error occurred while retrieving logs for build {build_id}: {e}")
        return None
def _parse_terraform_log(log_text: str, command: str) -> str:
    """Parses Terraform logs to find the plan summary or apply output."""
    if not log_text:
        return f"Could not retrieve logs to parse for Terraform {command} result."

    if command == "plan":
        # Look for the "Plan: X to add, Y to change, Z to destroy." line
        match = re.search(r"Plan: (\d+ to add, \d+ to change, \d+ to destroy\.)", log_text)
        if match:
            return f"Terraform Plan Summary: {match.group(1)}"
        return "Terraform plan ran, but summary line could not be found in logs."
        
    if command == "apply -auto-approve":
        # Look for the "Outputs:" section and the service_url - improved regex
        # The logs show: service_url = "https://staging-service-1750243796-cdoz2wv6ia-uc.a.run.app"
        match = re.search(r'service_url\s*=\s*"(https://[^"]+)"', log_text)
        if match:
            return f"Terraform apply complete. New service URL: {match.group(1)}"
        
        # Alternative patterns to try
        match = re.search(r'service_url\s*=\s*(https://\S+)', log_text)
        if match:
            return f"Terraform apply complete. New service URL: {match.group(1)}"
            
        # Check if apply was successful but just can't find the URL
        if "Apply complete!" in log_text:
            return "Terraform apply completed successfully, but service_url output could not be parsed from logs."
        
        return "Terraform apply status unclear from logs."
    
    return "Unknown command for log parsing."

def _summarize_terraform_output_with_gemini(log_text: str, command: str) -> str:
    """Uses Gemini to summarize Terraform output."""
    if not log_text:
        return "No log content available for summarization."
        
    if not gemini_client:
        logging.warning("Infra Agent: Gemini client not configured, cannot summarize terraform output.")
        return "Gemini summarization not available."
        
    try:
        prompt = f"""You are a helpful DevOps assistant. Summarize the following Terraform {command} output. 
Be concise and highlight the key changes, resources affected, and any important outputs or warnings:

Terraform {command} output:
{log_text[:2000]}
"""
        
        logging.info(f"Infra Agent: Sending terraform {command} output to Gemini for summarization...")
        
        if gemini_client == "vertex":
            # Use Vertex AI
            from vertexai.generative_models import GenerativeModel
            model = GenerativeModel(GEMINI_MODEL_NAME)
            response = model.generate_content(prompt)
            summary = response.text
        else:
            # Use direct Gemini API
            model = gemini_client.GenerativeModel(GEMINI_MODEL_NAME)
            response = model.generate_content(prompt)
            summary = response.text
            
        logging.info("Infra Agent: Gemini summarization successful.")
        return summary
        
    except Exception as e:
        logging.error(f"Infra Agent: Error during Gemini summarization: {e}")
        return f"Could not summarize terraform output due to an error: {e}."

def _run_terraform_trigger(command: str, new_service_name: str, deployment_image_uri: str, region: str) -> dict:
    """Helper function to run the Terraform trigger and process results."""
    logging.info(f"Infra Agent: Invoking Terraform trigger for command '{command}' on service '{new_service_name}'.")
    
    client = cloudbuild_v1.CloudBuildClient()

    source = cloudbuild_v1.types.RepoSource(
        repo_name=TERRAFORM_SOURCE_REPO,
        branch_name="main",
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
        build_id = result.id
        log_url = result.log_url
        logging.info(f"Infra Agent: Terraform trigger run completed. Status: {result.status}. Logs at: {log_url}")

        # Get logs using the new simplified and robust function
        log_text = _get_build_logs(result)

        if result.status == cloudbuild_v1.Build.Status.SUCCESS:
            if log_text:
                # Save a copy for our records
                _save_log_archive(log_text, build_id, command)
                
                # Parse and analyze logs
                parsed_message = _parse_terraform_log(log_text, command)
                ai_summary = _summarize_terraform_output_with_gemini(log_text, command)
                
                return {
                    "status": "SUCCESS", 
                    "message": parsed_message,
                    "ai_summary": ai_summary,
                    "log_url": log_url,
                    "build_id": build_id,
                    "log_retrieved": True,
                    "logs_bucket": TERRAFORM_LOGS_BUCKET,
                    "log_path": f"terraform-logs/{command}/{build_id}/terraform_log.txt"
                }
            else:
                # Build succeeded but we couldn't get the logs
                return {
                    "status": "SUCCESS_NO_LOGS", 
                    "message": f"Terraform {command} completed successfully, but logs could not be retrieved from the build's log bucket.",
                    "ai_summary": "Logs not available for AI analysis.",
                    "log_url": log_url,
                    "build_id": build_id,
                    "log_retrieved": False,
                    "note": "Check the log_url manually for detailed output."
                }
        else: # Build failed
            error_message = f"Terraform {command} build failed. Check logs for details: {log_url}"
            if log_text:
                # If we got logs for the failure, add a summary
                _save_log_archive(log_text, build_id, command)
                ai_summary = _summarize_terraform_output_with_gemini(log_text, command)
                error_message += f"\n\nAI Analysis of Failure:\n{ai_summary}"

            return {
                "status": "FAILURE", 
                "error_message": error_message,
                "build_id": build_id,
                "log_url": log_url,
                "log_retrieved": log_text is not None,
            }

    except Exception as e:
        error_msg = f"Infra Agent: Failed to run Terraform trigger: {e}"
        logging.exception(error_msg)
        return {"status": "ERROR", "error_message": error_msg}
    
def run_terraform_plan(
    new_service_name: str,
    deployment_image_uri: str,
    region: str = "us-central1"
) -> dict:
    """Runs 'terraform plan' via a Cloud Build trigger and returns a summary of the plan."""
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
    """Runs 'terraform apply' via a Cloud Build trigger and returns the new service URL."""
    return _run_terraform_trigger(
        command="apply -auto-approve",
        new_service_name=new_service_name,
        deployment_image_uri=deployment_image_uri,
        region=region
    )

# --- ADK Agent Definition ---
infra_agent = LlmAgent(
    name="geminiflow_infrastructure_agent",
    model=GEMINI_MODEL_NAME,
    description="An agent that can provision new cloud environments and services using Terraform.",
    instruction="You are an Infrastructure Agent. Your job is to plan and apply infrastructure changes using Terraform based on user requests. You can analyze terraform logs and provide summaries. All logs are stored in and retrieved from the TERRAFORM_LOGS_BUCKET for consistent access.",
    tools=[
        run_terraform_plan,
        run_terraform_apply,
    ],
)

# --- Local Testing Example ---
if __name__ == "__main__":
    if not GCP_PROJECT_ID:
         print("Error: Please set GOOGLE_CLOUD_PROJECT environment variable.")
    elif not TERRAFORM_LOGS_BUCKET:
         print("Error: Please set TERRAFORM_LOGS_BUCKET environment variable.")
    else:
        print(f"Using TERRAFORM_LOGS_BUCKET: {TERRAFORM_LOGS_BUCKET}")
        test_image_for_new_service = "us-central1-docker.pkg.dev/geminiflow-461207/gemini-flow-apps/gemini-flow-hello-world:latest"
        new_service_name = f"staging-service-{int(time.time())}"

        print(f"--- Testing Infrastructure Agent Tools for new service: {new_service_name} ---")
        
        # Step 1: Run Terraform Plan
        plan_report = run_terraform_plan(
            new_service_name=new_service_name,
            deployment_image_uri=test_image_for_new_service
        )
        print("\n--- Terraform Plan Report ---")
        import json
        print(json.dumps(plan_report, indent=2))

        # Step 2: (Simulated Human Approval) Apply the plan
        if plan_report.get("status") in ["SUCCESS", "SUCCESS_NO_LOGS"]:
            print("\n--- Plan successful. Simulating human approval and running apply... ---")
            apply_report = run_terraform_apply(
                new_service_name=new_service_name,
                deployment_image_uri=test_image_for_new_service
            )
            print("\n--- Terraform Apply Report ---")
            print(json.dumps(apply_report, indent=2))
        else:
            print("\nSkipping apply due to plan failure or error.")