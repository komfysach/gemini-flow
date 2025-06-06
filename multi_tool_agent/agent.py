# moa_agent.py
# Agent Development Kit (ADK) Master Orchestrator Agent (MOA) for GeminiFlow

import os
import sys
import logging
from google.adk.agents import LlmAgent, Agent
from dotenv import load_dotenv
load_dotenv()

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.append(SCRIPT_DIR)

# --- Import sub-agent INSTANCES and their tool functions ---
try:
    from sca_agent import sca_agent, get_latest_commit_sha
    from bta_agent import bta_agent, trigger_build_and_monitor
    from da_agent import da_agent, deploy_to_cloud_run
    # Import MDA and its tools
    from mda_agent import mda_agent, get_cloud_run_metrics, get_cloud_run_logs, generate_health_report
    logging.info("MOA: Successfully imported SCA, BTA, DA, and MDA modules and agent instances.")
except ImportError as e:
    logging.error(f"Could not import sub-agents or their tool functions: {e}. Ensure agent files define agent instances and are accessible.")
    # Define dummy agents and functions if imports fail
    sca_agent = Agent(name="dummy_sca_agent", tools=[])
    bta_agent = Agent(name="dummy_bta_agent", tools=[])
    da_agent = Agent(name="dummy_da_agent", tools=[])
    mda_agent = LlmAgent(name="dummy_mda_agent", model="gemini-2.0-flash", tools=[]) # MDA is an LlmAgent
    def get_latest_commit_sha(repo_full_name: str, branch_name: str) -> dict:
        logging.warning("MOA: Using DUMMY get_latest_commit_sha due to import error.")
        return {"status": "ERROR", "error_message": "SCA module/tool function not found during MOA import."}
    def trigger_build_and_monitor(trigger_id: str, project_id: str, repo_name: str, branch_name: str, commit_sha: str = None) -> dict:
        logging.warning("MOA: Using DUMMY trigger_build_and_monitor due to import error.")
        return {"status": "ERROR", "error_message": "BTA module/tool function not found during MOA import."}
    def deploy_to_cloud_run(project_id: str, region: str, service_name: str, image_uri: str) -> dict:
        logging.warning("MOA: Using DUMMY deploy_to_cloud_run due to import error.")
        return {"status": "ERROR", "error_message": "DA module/tool function not found during MOA import."}
    def get_cloud_run_metrics(project_id: str, service_id: str, location: str, time_window_minutes: int = 15) -> dict:
        logging.warning("MOA: Using DUMMY get_cloud_run_metrics due to import error.")
        return {"status": "ERROR", "error_message": "MDA metrics tool function not found."}
    def get_cloud_run_logs(project_id: str, service_id: str, location: str, time_window_minutes: int = 15, max_entries: int = 10) -> dict:
        logging.warning("MOA: Using DUMMY get_cloud_run_logs due to import error.")
        return {"status": "ERROR", "error_message": "MDA logs tool function not found."}
    def generate_health_report(service_id: str, metrics_report: dict, logs_report: dict) -> str:
        logging.warning("MOA: Using DUMMY generate_health_report due to import error.")
        return "Error: MDA report generation tool function not found."

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
if 'mda_agent' not in globals() or mda_agent.name == "dummy_mda_agent":
     logging.warning("MOA: Imports for MDA might have failed. Using dummy fallbacks.")


# --- MOA Configuration ---
GCP_PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT")
TARGET_GITHUB_REPO_FULL_NAME = os.getenv("TARGET_GITHUB_REPO", "your_github_username/gemini-flow-hello-world") # REPLACE
TARGET_APP_TRIGGER_ID = os.getenv("TARGET_APP_TRIGGER_ID", "your-geminiflow-hello-world-trigger-id") # REPLACE
TARGET_APP_CLOUD_RUN_REGION = os.getenv("TARGET_APP_CLOUD_RUN_REGION", "us-central1")
TARGET_APP_CLOUD_RUN_SERVICE_NAME = os.getenv("TARGET_APP_CLOUD_RUN_SERVICE_NAME", "geminiflow-hello-world-svc")

# --- MOA Tool Definitions ---
def execute_smart_deploy_workflow(
    target_repository_name: str,
    target_branch_name: str
) -> str:
    """
    Orchestrates the full CI/CD pipeline by calling functions that represent specialized agent logic.
    """
    if not GCP_PROJECT_ID:
        return "Error: GCP_PROJECT_ID is not configured for MOA."
    if TARGET_GITHUB_REPO_FULL_NAME == "your_github_username/gemini-flow-hello-world" or \
       TARGET_APP_TRIGGER_ID == "your-geminiflow-hello-world-trigger-id":
        return "Error: MOA target repository or trigger ID is not configured correctly. Please update environment variables or script defaults."

    logging.info(f"MOA Tool (Smart Deploy): Initiating for repo '{target_repository_name}' on branch '{target_branch_name}'.")
    final_summary = []

    if target_repository_name.lower() != "gemini-flow-hello-world":
        msg = f"MOA Tool (Smart Deploy): Deployment for repository '{target_repository_name}' is not configured. Only 'gemini-flow-hello-world' is supported."
        logging.warning(msg)
        return msg

    current_repo_full_name = TARGET_GITHUB_REPO_FULL_NAME

    logging.info(f"MOA Tool (Smart Deploy): Using SCA's logic for latest commit...")
    sca_report = get_latest_commit_sha(repo_full_name=current_repo_full_name, branch_name=target_branch_name)
    final_summary.append(f"SCA Logic Report: {sca_report.get('message', sca_report.get('error_message', 'No details'))}")
    if sca_report.get("status") != "SUCCESS":
        # ... (error handling) ...
        error_msg = f"MOA Tool (Smart Deploy): SCA logic failed. Halting. Reason: {sca_report.get('error_message', 'Unknown SCA error')}"
        logging.error(error_msg)
        final_summary.append(f"Deployment HALTED: {error_msg}")
        return "\n".join(final_summary)
    commit_sha = sca_report.get("commit_sha")
    logging.info(f"MOA Tool (Smart Deploy): SCA logic successful. Commit SHA: {commit_sha}")

    logging.info(f"MOA Tool (Smart Deploy): Using BTA's logic to trigger build...")
    bta_report = trigger_build_and_monitor(
        trigger_id=TARGET_APP_TRIGGER_ID, project_id=GCP_PROJECT_ID,
        repo_name=current_repo_full_name.split('/')[-1], branch_name=target_branch_name, commit_sha=commit_sha
    )
    final_summary.append(f"BTA Logic Report: {bta_report.get('message', bta_report.get('error_message', 'No details'))}")
    if bta_report.get("status") != "SUCCESS":
        # ... (error handling) ...
        error_msg = f"MOA Tool (Smart Deploy): BTA logic failed. Halting. Reason: {bta_report.get('error_message', 'Unknown BTA error')}"
        logging.error(error_msg)
        final_summary.append(f"Deployment HALTED: {error_msg}")
        return "\n".join(final_summary)
    image_uri_commit = bta_report.get("image_uri_commit")
    if not image_uri_commit:
        # ... (error handling) ...
        error_msg = "MOA Tool (Smart Deploy): BTA logic succeeded but no image URI returned. Halting."
        logging.error(error_msg)
        final_summary.append(f"Deployment HALTED: {error_msg}")
        return "\n".join(final_summary)
    logging.info(f"MOA Tool (Smart Deploy): BTA logic successful. Image URI: {image_uri_commit}")

    logging.info(f"MOA Tool (Smart Deploy): Using DA's logic to deploy image...")
    da_report = deploy_to_cloud_run(
        project_id=GCP_PROJECT_ID, region=TARGET_APP_CLOUD_RUN_REGION,
        service_name=TARGET_APP_CLOUD_RUN_SERVICE_NAME, image_uri=image_uri_commit
    )
    final_summary.append(f"DA Logic Report: {da_report.get('message', da_report.get('error_message', 'No details'))}")
    if da_report.get("status") != "SUCCESS":
        # ... (error handling) ...
        error_msg = f"MOA Tool (Smart Deploy): DA logic failed. Deployment unsuccessful. Reason: {da_report.get('error_message', 'Unknown DA error')}"
        logging.error(error_msg)
        final_summary.append(f"Deployment FAILED: {error_msg}")
        return "\n".join(final_summary)
    service_url = da_report.get("service_url")
    success_msg = f"MOA Tool (Smart Deploy): DA logic successful. App '{target_repository_name}' deployed. URL: {service_url}"
    logging.info(success_msg)
    final_summary.append(f"Deployment SUCCESSFUL: {success_msg}")
    return "\n".join(final_summary)


def execute_health_check_workflow(
    service_id: str,
    location: str,
    time_window_minutes: int = 15, # Default time window for the workflow
    max_log_entries: int = 5      # Default max log entries for the workflow
) -> str:
    """
    Orchestrates fetching metrics and logs for a service and generating a raw health report string.
    The MOA's LLM will then summarize this raw report.

    Args:
        service_id (str): The Cloud Run service ID (e.g., "geminiflow-hello-world-svc").
        location (str): The Cloud Run service location/region (e.g., "us-central1").
        time_window_minutes (int): How many minutes back to look for metrics and logs.
        max_log_entries (int): Max number of log entries to include in the report.

    Returns:
        str: A formatted string containing the raw health data, or an error message.
             This string is intended to be summarized by the MOA's LLM.
    """
    if not GCP_PROJECT_ID:
        return "Error: GCP_PROJECT_ID is not configured for MOA."
    if not service_id or not location:
        return "Error: Service ID and Location are required for health check."

    logging.info(f"MOA Tool (Health Check): Initiating for service '{service_id}' in '{location}'.")

    # Step 1: Call MDA's get_cloud_run_metrics tool function
    logging.info(f"MOA Tool (Health Check): Fetching metrics for {service_id}...")
    metrics_report = get_cloud_run_metrics(
        project_id=GCP_PROJECT_ID,
        service_id=service_id,
        location=location,
        time_window_minutes=time_window_minutes
    )

    # Step 2: Call MDA's get_cloud_run_logs tool function
    logging.info(f"MOA Tool (Health Check): Fetching logs for {service_id}...")
    logs_report = get_cloud_run_logs(
        project_id=GCP_PROJECT_ID,
        service_id=service_id,
        location=location,
        time_window_minutes=time_window_minutes,
        max_entries=max_log_entries
    )

    # Step 3: Call MDA's generate_health_report tool function (which formats data)
    logging.info(f"MOA Tool (Health Check): Compiling raw data for {service_id}...")
    raw_data_report_string = generate_health_report(
        service_id=service_id,
        metrics_report=metrics_report,
        logs_report=logs_report
    )
    
    # This raw data string will be returned. The MOA's LLM is responsible for summarizing it.
    logging.info(f"MOA Tool (Health Check): Raw data report compiled for {service_id}.")
    return raw_data_report_string


# --- ADK Agent Definition for MOA ---
root_agent = LlmAgent(
    name="geminiflow_master_orchestrator_agent",
    model="gemini-2.0-flash",
    description=(
        "The Master Orchestrator Agent for the GeminiFlow DevOps Co-Pilot. "
        "It understands user requests for CI/CD operations and health checks, "
        "and coordinates its sub-agents (SCA, BTA, DA, MDA) by using its specialized workflow tools."
    ),
    instruction=(
        "You are the Master Orchestrator for a DevOps CI/CD system called GeminiFlow. "
        "You have specialized sub-agents: Source Control (SCA), Build & Test (BTA), Deployment (DA), "
        "and Monitoring & Diagnostics (MDA). Your primary roles are to manage deployments and provide health checks. "
        "\n1. For DEPLOYMENTS: When a user asks to deploy an application (e.g., 'Deploy gemini-flow-hello-world from main'), "
        "identify the repository name and branch. Then, use the 'execute_smart_deploy_workflow' tool with "
        "target_repository_name and target_branch_name. Assume 'gemini-flow-hello-world' is the primary application. "
        "After the tool runs, summarize its string output for the user."
        "\n2. For HEALTH CHECKS: When a user asks for the health or status of a service (e.g., 'What's the health of gemini-flow-hello-world-svc in us-central1?'), "
        "identify the service_id and location. Then, use the 'execute_health_check_workflow' tool. "
        "The tool will return a string containing raw metrics and logs. You MUST then summarize this raw data string "
        "into a concise, human-readable health report for the user. Highlight any significant errors, high error rates, or performance issues. "
        "If data couldn't be fetched, mention that. Default service is 'geminiflow-hello-world-svc' in 'us-central1' if not specified."
    ),
    tools=[
        execute_smart_deploy_workflow,
        execute_health_check_workflow # Added new tool
    ],
    sub_agents=[sca_agent, bta_agent, da_agent, mda_agent] # Added mda_agent
)

# --- Local Testing ---
if __name__ == "__main__":
    # ... (setup checks from before) ...
    if not GCP_PROJECT_ID:
        print("MOA Test Error: GOOGLE_CLOUD_PROJECT environment variable is not set.")
    elif os.getenv("GOOGLE_CLOUD_LOCATION") is None:
        print("MOA Test Error: GOOGLE_CLOUD_LOCATION environment variable for Vertex AI is not set (e.g., 'us-central1').")
    elif TARGET_GITHUB_REPO_FULL_NAME == "your_github_username/gemini-flow-hello-world" or \
         TARGET_APP_TRIGGER_ID == "your-geminiflow-hello-world-trigger-id":
        print("MOA Test Error: Please update TARGET_GITHUB_REPO_FULL_NAME and TARGET_APP_TRIGGER_ID in the moa_agent.py script or via .env file with your actual values.")
    else:
        print("--- Testing MOA ---")
        
        # Option 1: Test the Python orchestration logic directly (bypasses LLM)
        print("\n--- Option 1a: Direct Test of 'execute_smart_deploy_workflow' tool ---")
        test_repo = "gemini-flow-hello-world"
        test_branch = "main" # or "main"
        print(f"Calling tool directly for repo: {test_repo}, branch: {test_branch}")
        try:
            tool_summary = execute_smart_deploy_workflow(
                target_repository_name=test_repo,
                target_branch_name=test_branch
            )
            print("\nTool Execution Summary (Smart Deploy - Direct Call):")
            print(tool_summary)
        except Exception as e:
            print(f"Error during direct smart deploy tool call: {e}")
            logging.exception("Direct smart deploy tool call failed")

        print("\n--- Option 1b: Direct Test of 'execute_health_check_workflow' tool ---")
        test_service_id = TARGET_APP_CLOUD_RUN_SERVICE_NAME
        test_location = TARGET_APP_CLOUD_RUN_REGION
        print(f"Calling health check tool directly for service: {test_service_id} in {test_location}")
        try:
            health_data_summary = execute_health_check_workflow(
                service_id=test_service_id,
                location=test_location,
                time_window_minutes=5, # Keep it short for testing
                max_log_entries=3
            )
            print("\nRaw Health Data Summary (Direct Call):")
            print(health_data_summary)
            print("\nNOTE: The above is RAW data. When run via ADK CLI, the MOA's LLM should summarize this.")
        except Exception as e:
            print(f"Error during direct health check tool call: {e}")
            logging.exception("Direct health check tool call failed")


        # Option 2: Test the LlmAgent (moa_agent) using ADK CLI
        print("\n--- Option 2: Testing LlmAgent (moa_agent) with ADK CLI ---")
        print("To test the full LlmAgent (including LLM decision-making and tool use):")
        print("1. Make sure this file is named 'agent.py' OR your __init__.py correctly exposes 'moa_agent' as 'agent' or 'root_agent'.")
        print("2. Ensure sca_agent.py, bta_agent.py, da_agent.py, mda_agent.py are in the same directory.")
        print("3. Navigate to this directory in your terminal.")
        print("4. Run the command: adk run .")
        print("5. In the interactive prompt, try queries like:")
        print("   User: Please deploy gemini-flow-hello-world from the master branch.")
        print(f"   User: What is the health of {TARGET_APP_CLOUD_RUN_SERVICE_NAME} in {TARGET_APP_CLOUD_RUN_REGION}?")
        print("Ensure all environment variables are set in the terminal session where you run 'adk run .'.")