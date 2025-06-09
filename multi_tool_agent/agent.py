# Agent Development Kit (ADK) Master Orchestrator Agent (MOA) for GeminiFlow

import os
import sys
import logging
from google.adk.agents import LlmAgent, Agent
from dotenv import load_dotenv
load_dotenv()

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

# --- Import sub-agent INSTANCES and their tool functions ---
try:
    from sca_agent import sca_agent, get_latest_commit_sha
    from bta_agent import bta_agent, trigger_build_and_monitor
    from da_agent import da_agent, deploy_to_cloud_run
    from mda_agent import mda_agent, get_cloud_run_metrics, get_cloud_run_logs, generate_health_report
    # Import FinOps agent and its tools
    from finops_agent import finops_agent, get_total_project_cost, get_cost_by_service
    logging.info("MOA: Successfully imported SCA, BTA, DA, MDA, and FinOps modules and agent instances.")
except ImportError as e:
    logging.error(f"Could not import sub-agents or their tool functions: {e}. Ensure agent files define agent instances and are accessible.")
    # Define dummy agents and functions if imports fail
    sca_agent = Agent(name="dummy_sca_agent", tools=[])
    bta_agent = Agent(name="dummy_bta_agent", tools=[])
    da_agent = Agent(name="dummy_da_agent", tools=[])
    mda_agent = LlmAgent(name="dummy_mda_agent", model="gemini-2.0-flash", tools=[])
    finops_agent = Agent(name="dummy_finops_agent", tools=[])
    def get_latest_commit_sha(repo_full_name: str, branch_name: str) -> dict:
        return {"status": "ERROR", "error_message": "SCA module/tool function not found during MOA import."}
    def trigger_build_and_monitor(trigger_id: str, project_id: str, repo_name: str, branch_name: str, commit_sha: str = None) -> dict:
        return {"status": "ERROR", "error_message": "BTA module/tool function not found during MOA import."}
    def deploy_to_cloud_run(project_id: str, region: str, service_name: str, image_uri: str) -> dict:
        return {"status": "ERROR", "error_message": "DA module/tool function not found during MOA import."}
    def get_cloud_run_metrics(project_id: str, service_id: str, location: str, time_window_minutes: int = 15) -> dict:
        return {"status": "ERROR", "error_message": "MDA metrics tool function not found."}
    def get_cloud_run_logs(project_id: str, service_id: str, location: str, time_window_minutes: int = 15, max_entries: int = 10) -> dict:
        return {"status": "ERROR", "error_message": "MDA logs tool function not found."}
    def generate_health_report(service_id: str, metrics_report: dict, logs_report: dict) -> str:
        return "Error: MDA report generation tool function not found."
    def get_total_project_cost(days_ago: int = 7) -> dict:
        return {"status": "ERROR", "error_message": "FinOps total cost tool function not found."}
    def get_cost_by_service(days_ago: int = 7, limit: int = 5) -> dict:
        return {"status": "ERROR", "error_message": "FinOps cost by service tool function not found."}

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


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
    logging.info(f"MOA Tool (Smart Deploy): Initiating for repo '{target_repository_name}' on branch '{target_branch_name}'.")
    sca_report = get_latest_commit_sha(repo_full_name=TARGET_GITHUB_REPO_FULL_NAME, branch_name=target_branch_name)
    if sca_report.get("status") != "SUCCESS":
        return f"Deployment HALTED at SCA step. Reason: {sca_report.get('error_message')}"
    commit_sha = sca_report.get("commit_sha")

    bta_report = trigger_build_and_monitor(
        trigger_id=TARGET_APP_TRIGGER_ID, project_id=GCP_PROJECT_ID,
        repo_name=TARGET_GITHUB_REPO_FULL_NAME.split('/')[-1], branch_name=target_branch_name, commit_sha=commit_sha
    )
    if bta_report.get("status") != "SUCCESS":
        return f"Deployment HALTED at BTA step. Reason: {bta_report.get('error_message')}"
    image_uri_commit = bta_report.get("image_uri_commit")

    da_report = deploy_to_cloud_run(
        project_id=GCP_PROJECT_ID, region=TARGET_APP_CLOUD_RUN_REGION,
        service_name=TARGET_APP_CLOUD_RUN_SERVICE_NAME, image_uri=image_uri_commit
    )
    if da_report.get("status") != "SUCCESS":
        return f"Deployment FAILED at DA step. Reason: {da_report.get('error_message')}"
        
    return f"Deployment SUCCESSFUL. Service URL: {da_report.get('service_url')}. Test results: {bta_report.get('test_results', {}).get('failure_summary', 'Not available')}"


def execute_health_check_workflow(
    service_id: str,
    location: str,
    time_window_minutes: int = 15,
    max_log_entries: int = 5
) -> str:
    logging.info(f"MOA Tool (Health Check): Initiating for service '{service_id}' in '{location}'.")
    metrics_report = get_cloud_run_metrics(
        project_id=GCP_PROJECT_ID, service_id=service_id, location=location,
        time_window_minutes=time_window_minutes
    )
    logs_report = get_cloud_run_logs(
        project_id=GCP_PROJECT_ID, service_id=service_id, location=location,
        time_window_minutes=time_window_minutes, max_entries=max_log_entries
    )
    raw_data_report_string = generate_health_report(
        service_id=service_id, metrics_report=metrics_report, logs_report=logs_report
    )
    logging.info(f"MOA Tool (Health Check): Raw data report compiled for {service_id}.")
    return raw_data_report_string

def execute_finops_report_workflow(
    days_ago: int = 7
) -> str:
    """
    Orchestrates fetching cost data and formats it into a string for the LLM to summarize.

    Args:
        days_ago (int): The number of days to look back for cost data.

    Returns:
        str: A formatted string containing raw cost data, or an error message.
    """
    logging.info(f"MOA Tool (FinOps): Initiating cost report for the last {days_ago} days.")
    
    # Call the tools from the FinOps agent's logic
    total_cost_report = get_total_project_cost(days_ago=days_ago)
    cost_by_service_report = get_cost_by_service(days_ago=days_ago)
    
    # Format the combined results into a single string for the LLM
    report_parts = [f"FinOps Report Data (last {days_ago} days):\n"]
    
    if total_cost_report.get("status") == "SUCCESS":
        report_parts.append(f"Total Cost: {total_cost_report.get('total_cost', 'N/A')}")
    else:
        report_parts.append(f"Total Cost: Error - {total_cost_report.get('error_message', 'Could not fetch total cost.')}")
        
    if cost_by_service_report.get("status") == "SUCCESS":
        cost_breakdown = cost_by_service_report.get('cost_breakdown', [])
        report_parts.append("\nTop Services by Cost:")
        if cost_breakdown:
            for service in cost_breakdown:
                report_parts.append(f"  - {service.get('service_name')}: {service.get('total_cost')}")
        else:
            report_parts.append("  - No cost data found for services.")
    else:
        report_parts.append(f"\nTop Services by Cost: Error - {cost_by_service_report.get('error_message', 'Could not fetch cost breakdown.')}")

    return "\n".join(report_parts)


# --- ADK Agent Definition for MOA ---
root_agent = LlmAgent(
    name="geminiflow_master_orchestrator_agent",
    model="gemini-2.0-flash",
    description=(
        "The Master Orchestrator Agent for the GeminiFlow DevOps Co-Pilot. "
        "It understands user requests for CI/CD operations, health checks, and cost reports, "
        "and coordinates its sub-agents by using its specialized workflow tools."
    ),
    instruction=(
        "You are the Master Orchestrator for a DevOps & FinOps system called GeminiFlow. "
        "You have specialized sub-agents. Your primary roles are to manage deployments, provide health checks, and report on costs. "
        "\n1. For DEPLOYMENTS: When a user asks to deploy an application (e.g., 'Deploy gemini-flow-hello-world from main'), "
        "identify the repository name and branch. Then, use the 'execute_smart_deploy_workflow' tool. "
        "\n2. For HEALTH CHECKS: When a user asks for the health or status of a service (e.g., 'What's the health of gemini-flow-hello-world-svc?'), "
        "identify the service_id and location. Then, use the 'execute_health_check_workflow' tool. The tool will return raw data; you MUST summarize this raw data into a concise, human-readable health report."
        "\n3. For COST REPORTS: When a user asks about costs or spending (e.g., 'How much did we spend last week?' or 'give me a cost breakdown'), "
        "determine the time window in days. Then, use the 'execute_finops_report_workflow' tool with the 'days_ago' parameter. "
        "The tool will return raw cost data; you MUST summarize this raw data into a friendly, human-readable cost report."
    ),
    tools=[
        execute_smart_deploy_workflow,
        execute_health_check_workflow,
        execute_finops_report_workflow # Added new tool
    ],
    sub_agents=[sca_agent, bta_agent, da_agent, mda_agent, finops_agent] # Added finops_agent
)

# --- Local Testing ---
if __name__ == "__main__":
    # ... setup checks ...
    if not GCP_PROJECT_ID:
        print("MOA Test Error: GOOGLE_CLOUD_PROJECT environment variable is not set.")
    else:
        # Test FinOps tool directly
        print("\n--- Direct Test of 'execute_finops_report_workflow' tool ---")
        try:
            cost_data = execute_finops_report_workflow(days_ago=30)
            print("\nRaw Cost Data Summary (Direct Call):")
            print(cost_data)
            print("\nNOTE: The above is RAW data. When run via ADK CLI, the MOA's LLM should summarize this.")
        except Exception as e:
            print(f"Error during direct FinOps tool call: {e}")
            logging.exception("Direct FinOps tool call failed")
        
        # Instructions for testing with ADK CLI
        print("\n\n--- To Test Full LlmAgent (MOA) with ADK CLI ---")
        print("1. Ensure all agent .py files are in the same directory.")
        print("2. In your terminal, cd to this directory.")
        print("3. Set ALL required environment variables.")
        print("4. Run: adk run .")
        print("5. At the 'User:' prompt, try queries like:")
        print("   User: deploy gemini-flow-hello-world from master")
        print("   User: what is the health of geminiflow-hello-world-svc in us-central1")
        print("   User: how much have we spent in the last 14 days")
