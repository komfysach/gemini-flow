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

def _get_build_logs_from_api(build_id: str) -> str | None:
    """
    Get build logs directly from Cloud Build API.
    """
    try:
        logging.info(f"Infra Agent: Fetching logs for build {build_id} using Cloud Build API")
        client = cloudbuild_v1.CloudBuildClient()
        
        # Wait for build to complete and logs to be available
        max_attempts = 30  # Wait up to 5 minutes
        for attempt in range(max_attempts):
            try:
                build = client.get_build(project_id=GCP_PROJECT_ID, id=build_id)
                
                if build.status in [cloudbuild_v1.Build.Status.SUCCESS, 
                                   cloudbuild_v1.Build.Status.FAILURE, 
                                   cloudbuild_v1.Build.Status.TIMEOUT,
                                   cloudbuild_v1.Build.Status.CANCELLED]:
                    # Build is complete, try to get logs
                    if hasattr(build, 'log_url') and build.log_url:
                        # Try to extract logs from GCS if log_url contains GCS path
                        logs = _extract_logs_from_build_object(build)
                        if logs:
                            return logs
                    
                    # Fallback: try to get logs from steps
                    step_logs = _extract_step_logs(build)
                    if step_logs:
                        return step_logs
                        
                    logging.warning(f"Infra Agent: Build {build_id} completed but no logs found")
                    break
                else:
                    logging.info(f"Infra Agent: Build {build_id} still running (status: {build.status}), attempt {attempt + 1}/{max_attempts}")
                    time.sleep(10)
                    
            except Exception as e:
                logging.warning(f"Infra Agent: Error getting build {build_id} on attempt {attempt + 1}: {e}")
                time.sleep(10)
                
        return None
        
    except Exception as e:
        logging.error(f"Infra Agent: Failed to get build logs from API: {e}")
        return None

def _extract_logs_from_build_object(build) -> str | None:
    """
    Extract logs from the build object using various methods.
    """
    try:
        # Method 1: Check if logs are stored in GCS bucket
        if hasattr(build, 'logs_bucket') and build.logs_bucket:
            logs_bucket = build.logs_bucket
            build_id = build.id
            
            storage_client = storage.Client(project=GCP_PROJECT_ID)
            
            # Try different log file patterns
            log_patterns = [
                f"log-{build_id}.txt",
                f"{build_id}.txt",
                f"logs/{build_id}.txt",
                f"build-logs/{build_id}.txt"
            ]
            
            for pattern in log_patterns:
                try:
                    bucket = storage_client.bucket(logs_bucket)
                    blob = bucket.blob(pattern)
                    
                    if blob.exists():
                        content = blob.download_as_text()
                        logging.info(f"Infra Agent: Found logs at gs://{logs_bucket}/{pattern}")
                        return content
                        
                except Exception as e:
                    logging.debug(f"Infra Agent: Could not access gs://{logs_bucket}/{pattern}: {e}")
                    continue
        
        # Method 2: Try to get logs from Cloud Logging
        return _get_logs_from_cloud_logging(build.id)
        
    except Exception as e:
        logging.warning(f"Infra Agent: Error extracting logs from build object: {e}")
        return None

def _get_logs_from_cloud_logging(build_id: str) -> str | None:
    """
    Fetch logs from Cloud Logging using the build ID.
    """
    try:
        from google.cloud import logging as cloud_logging
        
        logging.info(f"Infra Agent: Attempting to fetch logs from Cloud Logging for build {build_id}")
        
        client = cloud_logging.Client(project=GCP_PROJECT_ID)
        
        # Query for Cloud Build logs
        filter_str = f'''
        resource.type="build"
        resource.labels.build_id="{build_id}"
        logName="projects/{GCP_PROJECT_ID}/logs/cloudbuild"
        '''
        
        entries = list(client.list_entries(filter_=filter_str, order_by=cloud_logging.ASCENDING))
        
        if entries:
            log_lines = []
            for entry in entries:
                if hasattr(entry, 'payload') and entry.payload:
                    log_lines.append(str(entry.payload))
                elif hasattr(entry, 'text_payload') and entry.text_payload:
                    log_lines.append(entry.text_payload)
                    
            if log_lines:
                full_log = '\n'.join(log_lines)
                logging.info(f"Infra Agent: Retrieved {len(log_lines)} log entries from Cloud Logging")
                return full_log
        
        logging.warning(f"Infra Agent: No logs found in Cloud Logging for build {build_id}")
        return None
        
    except Exception as e:
        logging.warning(f"Infra Agent: Could not fetch logs from Cloud Logging: {e}")
        return None

def _extract_step_logs(build) -> str | None:
    """
    Extract logs from individual build steps if available.
    """
    try:
        if hasattr(build, 'steps') and build.steps:
            step_logs = []
            for i, step in enumerate(build.steps):
                step_log = f"--- Step {i}: {getattr(step, 'name', 'unknown')} ---\n"
                
                # Add any step-specific information
                if hasattr(step, 'args') and step.args:
                    step_log += f"Args: {' '.join(step.args)}\n"
                    
                step_logs.append(step_log)
            
            if step_logs:
                return '\n'.join(step_logs)
                
    except Exception as e:
        logging.warning(f"Infra Agent: Error extracting step logs: {e}")
        
    return None

def _copy_logs_to_terraform_bucket(build_result, command: str) -> str | None:
    """
    Copies build logs from Cloud Build to TERRAFORM_LOGS_BUCKET and returns the content.
    This ensures we always have access to logs in our designated bucket.
    """
    build_id = build_result.id
    
    logging.info(f"Infra Agent: Copying logs for build {build_id} to TERRAFORM_LOGS_BUCKET")
    
    # Get the actual build logs (not the web console HTML)
    log_content = _get_build_logs_from_api(build_id)
    
    if log_content:
        # Save to our designated bucket
        if _save_log_to_terraform_bucket(log_content, build_id, command):
            logging.info(f"Infra Agent: Successfully copied logs to TERRAFORM_LOGS_BUCKET")
            return log_content
        else:
            logging.warning(f"Infra Agent: Retrieved logs but failed to save to TERRAFORM_LOGS_BUCKET")
            return log_content  # Still return the content even if save failed
    
    logging.error(f"Infra Agent: Could not retrieve logs for build {build_id}")
    return None

def _save_log_to_terraform_bucket(log_content: str, build_id: str, command: str) -> bool:
    """
    Saves log content to TERRAFORM_LOGS_BUCKET.
    """
    try:
        storage_client = storage.Client(project=GCP_PROJECT_ID)
        bucket = storage_client.bucket(TERRAFORM_LOGS_BUCKET)
        
        object_name = f"terraform-logs/{command}/{build_id}/terraform_log.txt"
        blob = bucket.blob(object_name)
        
        blob.upload_from_string(log_content)
        logging.info(f"Infra Agent: Saved log to gs://{TERRAFORM_LOGS_BUCKET}/{object_name}")
        return True
        
    except Exception as e:
        logging.error(f"Infra Agent: Failed to save log to TERRAFORM_LOGS_BUCKET: {e}")
        return False

def _get_logs_from_terraform_bucket(build_id: str, command: str) -> str | None:
    """
    Retrieves logs from TERRAFORM_LOGS_BUCKET.
    """
    try:
        storage_client = storage.Client(project=GCP_PROJECT_ID)
        bucket = storage_client.bucket(TERRAFORM_LOGS_BUCKET)
        
        object_name = f"terraform-logs/{command}/{build_id}/terraform_log.txt"
        blob = bucket.blob(object_name)
        
        if blob.exists():
            content = blob.download_as_text()
            logging.info(f"Infra Agent: Retrieved logs from gs://{TERRAFORM_LOGS_BUCKET}/{object_name}")
            return content
        else:
            logging.warning(f"Infra Agent: No logs found at gs://{TERRAFORM_LOGS_BUCKET}/{object_name}")
            return None
            
    except Exception as e:
        logging.error(f"Infra Agent: Error retrieving logs from TERRAFORM_LOGS_BUCKET: {e}")
        return None

def _download_gcs_artifact(bucket_name: str, object_name: str) -> str | None:
    """Downloads a file from GCS."""
    try:
        storage_client = storage.Client(project=GCP_PROJECT_ID)
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(object_name)
        
        logging.info(f"Infra Agent: Checking for artifact in GCS: bucket={bucket_name}, object={object_name}")
        
        if not blob.exists():
            logging.warning(f"Infra Agent: Artifact not found in GCS: gs://{bucket_name}/{object_name}")
            return None
            
        logging.info(f"Infra Agent: Downloading artifact gs://{bucket_name}/{object_name}")
        return blob.download_as_text()
        
    except Exception as e:
        logging.error(f"Infra Agent: Failed to download GCS artifact gs://{bucket_name}/{object_name}: {e}")
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
    logging.info(f"Infra Agent: Using TERRAFORM_LOGS_BUCKET: {TERRAFORM_LOGS_BUCKET}")
    
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

        if result.status == cloudbuild_v1.Build.Status.SUCCESS:
            # Step 1: Copy logs to TERRAFORM_LOGS_BUCKET
            log_text = _copy_logs_to_terraform_bucket(result, command)
            
            if log_text:
                # Step 2: Parse and analyze logs
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
                return {
                    "status": "SUCCESS_NO_LOGS", 
                    "message": f"Terraform {command} completed successfully, but logs could not be copied to {TERRAFORM_LOGS_BUCKET}.",
                    "ai_summary": "Logs not available for AI analysis.",
                    "log_url": log_url,
                    "build_id": build_id,
                    "log_retrieved": False,
                    "logs_bucket": TERRAFORM_LOGS_BUCKET,
                    "note": "Check the log_url manually for detailed output."
                }
        else:
            # Even for failures, try to get logs for debugging
            log_text = _copy_logs_to_terraform_bucket(result, command)
            
            return {
                "status": "FAILURE", 
                "error_message": f"Terraform {command} build failed. Check logs for details: {log_url}",
                "build_id": build_id,
                "log_url": log_url,
                "logs_bucket": TERRAFORM_LOGS_BUCKET,
                "log_retrieved": log_text is not None,
                "log_path": f"terraform-logs/{command}/{build_id}/terraform_log.txt" if log_text else None
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