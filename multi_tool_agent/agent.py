# moa_agent.py
# Agent Development Kit (ADK) Master Orchestrator Agent (MOA) for GeminiFlow

import os
import sys
import logging
from google.adk.agents import LlmAgent, Agent # Import Agent for sub_agents if they are not LlmAgents
from dotenv import load_dotenv
load_dotenv() # Load environment variables from .env file, if present

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.append(SCRIPT_DIR)

# --- Import sub-agent INSTANCES and their tool functions ---
# We need to import the actual agent instances to pass to sub_agents,
# and also their tool functions if the MOA's tool will call them directly.
try:
    from sca_agent import sca_agent, get_latest_commit_sha
    from bta_agent import bta_agent, trigger_build_and_monitor
    from da_agent import da_agent, deploy_to_cloud_run # Or deploy_to_cloud_run_v1
except ImportError as e:
    logging.error(f"Could not import sub-agents or their tool functions: {e}. Ensure agent files define agent instances and are accessible.")
    # Define dummy agents and functions if imports fail
    sca_agent = Agent(name="dummy_sca_agent", tools=[])
    bta_agent = Agent(name="dummy_bta_agent", tools=[])
    da_agent = Agent(name="dummy_da_agent", tools=[])
    def get_latest_commit_sha(repo_full_name: str, branch_name: str) -> dict:
        return {"status": "ERROR", "error_message": "SCA module not found."}
    def trigger_build_and_monitor(trigger_id: str, project_id: str, repo_name: str, branch_name: str, commit_sha: str = None) -> dict:
        return {"status": "ERROR", "error_message": "BTA module not found."}
    def deploy_to_cloud_run(project_id: str, region: str, service_name: str, image_uri: str) -> dict:
        return {"status": "ERROR", "error_message": "DA module not found."}

# Configure basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- MOA Configuration ---
GCP_PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT")
TARGET_GITHUB_REPO_FULL_NAME = os.getenv("TARGET_GITHUB_REPO", "your_github_username/gemini-flow-hello-world") # REPLACE
TARGET_APP_TRIGGER_ID = os.getenv("TARGET_APP_TRIGGER_ID", "your-geminiflow-hello-world-trigger-id") # REPLACE
TARGET_APP_CLOUD_RUN_REGION = os.getenv("TARGET_APP_CLOUD_RUN_REGION", "us-central1")
TARGET_APP_CLOUD_RUN_SERVICE_NAME = os.getenv("TARGET_APP_CLOUD_RUN_SERVICE_NAME", "geminiflow-hello-world-svc")

# --- MOA Tool Definition ---

def execute_smart_deploy_workflow(
    target_repository_name: str,
    target_branch_name: str
) -> str:
    """
    Orchestrates the full CI/CD pipeline by calling functions that represent specialized agent logic.
    1. Fetches the latest commit from GitHub using SCA's logic.
    2. Triggers a build and test pipeline using BTA's logic.
    3. Deploys the application using DA's logic if build is successful.
    """
    if not GCP_PROJECT_ID:
        return "Error: GCP_PROJECT_ID is not configured for MOA."
    if TARGET_GITHUB_REPO_FULL_NAME == "your_github_username/gemini-flow-hello-world" or \
       TARGET_APP_TRIGGER_ID == "your-geminiflow-hello-world-trigger-id":
        return "Error: MOA target repository or trigger ID is not configured correctly. Please update environment variables or script defaults."

    logging.info(f"MOA Tool: Initiating Smart Deploy for repo '{target_repository_name}' on branch '{target_branch_name}'.")
    final_summary = []

    if target_repository_name.lower() != "gemini-flow-hello-world": # Simple check for MVP
        msg = f"MOA Tool: Deployment for repository '{target_repository_name}' is not configured. Only 'gemini-flow-hello-world' is supported."
        logging.warning(msg)
        return msg

    current_repo_full_name = TARGET_GITHUB_REPO_FULL_NAME

    # Step 1: Simulate calling SCA's logic
    logging.info(f"MOA Tool: Using SCA's logic for latest commit on {current_repo_full_name}@{target_branch_name}...")
    sca_report = get_latest_commit_sha(
        repo_full_name=current_repo_full_name,
        branch_name=target_branch_name
    )
    final_summary.append(f"SCA Logic Report: {sca_report.get('message', sca_report.get('error_message', 'No details'))}")

    if sca_report.get("status") != "SUCCESS":
        error_msg = f"MOA Tool: SCA logic failed. Halting. Reason: {sca_report.get('error_message', 'Unknown SCA error')}"
        logging.error(error_msg)
        final_summary.append(f"Deployment HALTED: {error_msg}")
        return "\n".join(final_summary)
    
    commit_sha = sca_report.get("commit_sha")
    logging.info(f"MOA Tool: SCA logic successful. Commit SHA: {commit_sha}")

    # Step 2: Simulate calling BTA's logic
    logging.info(f"MOA Tool: Using BTA's logic to trigger build for commit '{commit_sha}'...")
    bta_report = trigger_build_and_monitor(
        trigger_id=TARGET_APP_TRIGGER_ID,
        project_id=GCP_PROJECT_ID,
        repo_name=current_repo_full_name.split('/')[-1],
        branch_name=target_branch_name,
        commit_sha=commit_sha
    )
    final_summary.append(f"BTA Logic Report: {bta_report.get('message', bta_report.get('error_message', 'No details'))}")

    if bta_report.get("status") != "SUCCESS":
        error_msg = f"MOA Tool: BTA logic failed. Halting. Reason: {bta_report.get('error_message', 'Unknown BTA error')}"
        logging.error(error_msg)
        final_summary.append(f"Deployment HALTED: {error_msg}")
        return "\n".join(final_summary)

    image_uri_commit = bta_report.get("image_uri_commit")
    if not image_uri_commit:
        error_msg = "MOA Tool: BTA logic succeeded but no image URI returned. Halting."
        logging.error(error_msg)
        final_summary.append(f"Deployment HALTED: {error_msg}")
        return "\n".join(final_summary)
    logging.info(f"MOA Tool: BTA logic successful. Image URI: {image_uri_commit}")

    # Step 3: Simulate calling DA's logic
    logging.info(f"MOA Tool: Using DA's logic to deploy image '{image_uri_commit}'...")
    da_report = deploy_to_cloud_run(
        project_id=GCP_PROJECT_ID,
        region=TARGET_APP_CLOUD_RUN_REGION,
        service_name=TARGET_APP_CLOUD_RUN_SERVICE_NAME,
        image_uri=image_uri_commit
    )
    final_summary.append(f"DA Logic Report: {da_report.get('message', da_report.get('error_message', 'No details'))}")

    if da_report.get("status") != "SUCCESS":
        error_msg = f"MOA Tool: DA logic failed. Deployment unsuccessful. Reason: {da_report.get('error_message', 'Unknown DA error')}"
        logging.error(error_msg)
        final_summary.append(f"Deployment FAILED: {error_msg}")
        return "\n".join(final_summary)

    service_url = da_report.get("service_url")
    success_msg = f"MOA Tool: DA logic successful. App '{target_repository_name}' deployed from branch '{target_branch_name}' (commit {commit_sha}). URL: {service_url}"
    logging.info(success_msg)
    final_summary.append(f"Deployment SUCCESSFUL: {success_msg}")
    
    return "\n".join(final_summary)


# --- ADK Agent Definition for MOA ---
# This is the LlmAgent instance.
root_agent = LlmAgent(
    name="geminiflow_master_orchestrator_agent",
    model="gemini-2.0-flash",
    description=(
        "The Master Orchestrator Agent for the GeminiFlow DevOps Co-Pilot. "
        "It understands user requests for CI/CD operations and coordinates its sub-agents (SCA, BTA, DA) "
        "by using its specialized workflow tool."
    ),
    instruction=(
        "You are the Master Orchestrator for a DevOps CI/CD system called GeminiFlow. "
        "You have specialized sub-agents: a Source Control Agent (SCA), a Build & Test Agent (BTA), "
        "and a Deployment Agent (DA), though your primary tool 'execute_smart_deploy_workflow' handles their logic. "
        "Your main role is to understand user requests related to deploying applications "
        "and then execute the 'Smart Deploy' workflow by calling the 'execute_smart_deploy_workflow' tool. "
        "When a user asks to deploy an application, identify the application's repository name "
        "and the branch they want to deploy from. Then, you must use the 'execute_smart_deploy_workflow' tool. "
        "For example, if the user says 'Deploy gemini-flow-hello-world from the main branch', "
        "call 'execute_smart_deploy_workflow' with target_repository_name='gemini-flow-hello-world' "
        "and target_branch_name='main'. "
        "Assume 'gemini-flow-hello-world' is the primary application. "
        "Provide a summary of the outcome to the user based on the tool's result."
    ),
    tools=[execute_smart_deploy_workflow],
    sub_agents=[sca_agent, bta_agent, da_agent] # Listing sub_agents for architectural clarity
)

# --- Local Testing ---
if __name__ == "__main__":
    # Before running:
    # 1. Ensure all sub-agent scripts (sca_agent.py, bta_agent.py, da_agent.py) define their
    #    respective agent instances (sca_agent, bta_agent, da_agent) at the module level
    #    and that their tool functions are correctly imported.
    # 2. Ensure these scripts are in PYTHONPATH or the same directory as moa_agent.py.
    # 3. Set GOOGLE_APPLICATION_CREDENTIALS for MOA (needs Vertex AI User for LlmAgent).
    #    The imported tool functions will use their own authentication methods (e.g., GITHUB_PAT
    #    for SCA, or ADC for BTA/DA if their respective GOOGLE_APPLICATION_CREDENTIALS are set
    #    when those modules are loaded/functions called, or if ADC picks up the MOA's key).
    # 4. Set GITHUB_PAT environment variable for SCA logic.
    # 5. Set GOOGLE_CLOUD_PROJECT environment variable.
    # 6. Update TARGET_GITHUB_REPO_FULL_NAME and TARGET_APP_TRIGGER_ID in this script's
    #    global constants or via a .env file to match your actual setup.

    if not GCP_PROJECT_ID:
        print("MOA Test Error: GOOGLE_CLOUD_PROJECT environment variable is not set.")
    elif TARGET_GITHUB_REPO_FULL_NAME == "your_github_username/gemini-flow-hello-world" or \
         TARGET_APP_TRIGGER_ID == "your-geminiflow-hello-world-trigger-id":
        print("MOA Test Error: Please update TARGET_GITHUB_REPO_FULL_NAME and TARGET_APP_TRIGGER_ID in the moa_agent.py script or via .env file with your actual values.")
    else:
        print("--- Testing MOA ---")
        
        # Option 1: Test the Python orchestration logic directly (bypasses LLM)
        print("\n--- Option 1: Direct Test of 'execute_smart_deploy_workflow' tool ---")
        # This tests your Python functions but not the LLM's decision to call the tool.
        test_repo = "gemini-flow-hello-world"
        test_branch = "main" # or "main"
        print(f"Calling tool directly for repo: {test_repo}, branch: {test_branch}")
        try:
            tool_summary = execute_smart_deploy_workflow(
                target_repository_name=test_repo,
                target_branch_name=test_branch
            )
            print("\nTool Execution Summary (Direct Call):")
            print(tool_summary)
        except Exception as e:
            print(f"Error during direct tool call: {e}")
            logging.exception("Direct tool call failed")

        # Option 2: Test the LlmAgent (moa_agent) using ADK CLI
        print("\n--- Option 2: Testing LlmAgent (moa_agent) with ADK CLI ---")
        print("To test the full LlmAgent (including LLM decision-making and tool use):")
        print("1. Make sure this file is named 'agent.py' OR your __init__.py correctly exposes 'moa_agent' as 'agent' or 'root_agent'.")
        print("2. Navigate to this directory in your terminal.")
        print("3. Run the command: adk run .")
        print("4. In the interactive prompt, type your query, e.g.:")
        print("   User: Please deploy gemini-flow-hello-world from the main branch.")
        print("The ADK runtime will handle the interaction with the LLM and tool execution.")
        print("Ensure all environment variables (GOOGLE_APPLICATION_CREDENTIALS for MOA, GITHUB_PAT for SCA, GOOGLE_CLOUD_PROJECT) are set in the terminal session where you run 'adk run .'.")