# agent.py
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
    from finops_agent import finops_agent, get_total_project_cost, get_cost_by_service
    from secops_agent import secops_agent, get_vulnerability_scan_results, summarize_vulnerabilities_with_gemini
    from rollback_agent import rollback_agent, get_previous_stable_revision, redirect_traffic_to_revision
    from infra_agent import infra_agent, run_terraform_plan, run_terraform_apply
    logging.info("MOA: Successfully imported SCA, BTA, DA, MDA, FinOps, Rollback modules and Security modules and agent instances.")
except ImportError as e:
    logging.error(f"Could not import sub-agents or their tool functions: {e}. Ensure agent files define agent instances and are accessible.")
    # Define dummy agents and functions if imports fail
    sca_agent = Agent(name="dummy_sca_agent", tools=[])
    bta_agent = Agent(name="dummy_bta_agent", tools=[])
    da_agent = Agent(name="dummy_da_agent", tools=[])
    mda_agent = LlmAgent(name="dummy_mda_agent", model="gemini-1.5-flash-latest", tools=[])
    finops_agent = Agent(name="dummy_finops_agent", tools=[])
    secops_agent = LlmAgent(name="dummy_secops_agent", model="gemini-1.5-flash-latest", tools=[])
    rollback_agent = Agent(name="dummy_rollback_agent", tools=[])
    infra_agent = Agent(name="dummy_infra_agent", tools=[])
    def get_latest_commit_sha(**kwargs): return {"status": "ERROR", "error_message": "SCA module not found."}
    def trigger_build_and_monitor(**kwargs): return {"status": "ERROR", "error_message": "BTA module not found."}
    def deploy_to_cloud_run(**kwargs): return {"status": "ERROR", "error_message": "DA module not found."}
    def get_cloud_run_metrics(**kwargs): return {"status": "ERROR", "error_message": "MDA module not found."}
    def get_cloud_run_logs(**kwargs): return {"status": "ERROR", "error_message": "MDA module not found."}
    def generate_health_report(**kwargs): return "Error: MDA module not found."
    def get_total_project_cost(**kwargs): return {"status": "ERROR", "error_message": "FinOps module not found."}
    def get_cost_by_service(**kwargs): return {"status": "ERROR", "error_message": "FinOps module not found."}
    def get_vulnerability_scan_results(**kwargs): return {"status": "ERROR", "error_message": "Security module not found."}
    def summarize_vulnerabilities_with_gemini(**kwargs): return "Error: Security module not found."
    def get_previous_stable_revision(**kwargs): return {"status": "ERROR", "error_message": "Rollback module not found."}
    def redirect_traffic_to_revision(**kwargs): return {"status": "ERROR", "error_message": "Rollback module not found."}
    def run_terraform_plan(**kwargs): return {"status": "ERROR", "error_message": "Infra module not found."}
    def run_terraform_apply(**kwargs): return {"status": "ERROR", "error_message": "Infra module not found."}

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


# --- MOA Configuration ---
GCP_PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT")
TARGET_GITHUB_REPO_FULL_NAME = os.getenv("TARGET_GITHUB_REPO", "komfysach/gemini-flow-hello-world")
TARGET_APP_TRIGGER_ID = os.getenv("TARGET_APP_TRIGGER_ID", "deploy-hello-world-app")
TARGET_APP_CLOUD_RUN_REGION = os.getenv("TARGET_APP_CLOUD_RUN_REGION", "us-central1")
TARGET_APP_CLOUD_RUN_SERVICE_NAME = os.getenv("TARGET_APP_CLOUD_RUN_SERVICE_NAME", "geminiflow-hello-world-svc")
INFRA_DEFAULT_IMAGE_REPO = os.getenv("ARTIFACT_REGISTRY_REPO", "gemini-flow-apps")
INFRA_DEFAULT_IMAGE_NAME = "gemini-flow-hello-world"

def execute_rollback_workflow(service_id: str, location: str) -> str:
    """
    Executes a full rollback workflow for a given service.
    """
    logging.warning(f"MOA Tool (Rollback): Initiating rollback for service '{service_id}' in '{location}'.")
    
    # Step 1: Find the revision to roll back to
    stable_rev_report = get_previous_stable_revision(
        project_id=GCP_PROJECT_ID,
        location=location,
        service_id=service_id
    )
    if stable_rev_report.get("status") != "SUCCESS":
        error_msg = f"Rollback FAILED: Could not identify a previous stable revision. Reason: {stable_rev_report.get('error_message')}"
        logging.error(error_msg)
        return error_msg
        
    revision_to_restore = stable_rev_report.get("previous_stable_revision_name")
    
    # Step 2: Redirect traffic
    redirect_report = redirect_traffic_to_revision(
        project_id=GCP_PROJECT_ID,
        location=location,
        service_id=service_id,
        revision_name=revision_to_restore
    )
    
    if redirect_report.get("status") == "SUCCESS":
        success_msg = f"Rollback SUCCESS: Traffic for '{service_id}' has been redirected to previous stable revision '{revision_to_restore.split('/')[-1]}'."
        logging.info(success_msg)
        return success_msg
    else:
        error_msg = f"Rollback FAILED: Attempted to redirect traffic, but failed. Reason: {redirect_report.get('error_message')}"
        logging.error(error_msg)
        return error_msg
    
def plan_new_environment(
    new_service_name: str,
    image_uri_to_deploy: str = "latest",
    region: str = TARGET_APP_CLOUD_RUN_REGION
) -> str:
    """
    Plans the creation of a new service environment using Terraform.
    If 'image_uri_to_deploy' is 'latest' or not provided, it uses the known latest image for gemini-flow-hello-world.
    """
    print(f"🎯 Starting Terraform plan for service '{new_service_name}'...")
    logging.info(f"MOA Tool (Infra Plan): Planning new service '{new_service_name}'.")

    final_image_uri = ""
    if image_uri_to_deploy.lower() == "latest":
        final_image_uri = (
            f"{TARGET_APP_CLOUD_RUN_REGION}-docker.pkg.dev/{GCP_PROJECT_ID}/"
            f"{INFRA_DEFAULT_IMAGE_REPO}/{INFRA_DEFAULT_IMAGE_NAME}:latest"
        )
        print(f"📦 Using default image URI: {final_image_uri}")
        logging.info(f"MOA Tool (Infra Plan): Using default image URI: {final_image_uri}")
    else:
        final_image_uri = image_uri_to_deploy
        print(f"📦 Using specified image URI: {final_image_uri}")
        logging.info(f"MOA Tool (Infra Plan): Using specific image URI provided: {final_image_uri}")

    print("⚙️ Executing Terraform plan operation...")
    plan_report = run_terraform_plan(
        new_service_name=new_service_name,
        deployment_image_uri=final_image_uri,
        region=region
    )

    if plan_report.get("status") not in ["SUCCESS", "SUCCESS_NO_LOGS"]:
        print(f"❌ Terraform plan failed: {plan_report.get('error_message')}")
        return f"Terraform plan FAILED. Reason: {plan_report.get('error_message')}"
    
    print("✅ Terraform plan completed successfully!")
    
    # Use the AI summary from the infra agent if available
    ai_summary = plan_report.get("ai_summary", "")
    parsed_message = plan_report.get("message", "")
    log_url = plan_report.get("log_url", "")
    build_id = plan_report.get("build_id", "")
    log_retrieved = plan_report.get("log_retrieved", False)
    
    response_parts = [
        f"✅ Terraform plan completed successfully for service '{new_service_name}'.",
        f"\n📋 Plan Summary: {parsed_message}"
    ]
    
    if ai_summary and ai_summary != "Gemini summarization not available.":
        response_parts.append(f"\n🤖 AI Analysis: {ai_summary}")
    
    if log_retrieved:
        logs_bucket = plan_report.get("logs_bucket", "")
        log_path = plan_report.get("log_path", "")
        response_parts.append(f"\n📁 Logs saved to: gs://{logs_bucket}/{log_path}")
    
    response_parts.extend([
        f"\n🔗 Build Details: {log_url}",
        f"\n🔧 Build ID: {build_id}",
        f"\n\n⚠️  Please review the plan details above before proceeding.",
        f"To apply this plan, respond with: 'apply the plan for {new_service_name}'"
    ])
    
    return "".join(response_parts)


def apply_new_environment(
    new_service_name: str,
    image_uri_to_deploy: str = "latest",
    region: str = TARGET_APP_CLOUD_RUN_REGION
) -> str:
    """
    Applies a Terraform plan to create a new service environment.
    This should be called after a plan has been reviewed and approved by the user.
    """
    print(f"🚀 Starting Terraform apply for service '{new_service_name}'...")
    print("⚠️  This will create real infrastructure resources. Please wait...")
    logging.info(f"MOA Tool (Infra Apply): Applying plan for new service '{new_service_name}'.")
    
    final_image_uri = ""
    if image_uri_to_deploy.lower() == "latest":
        final_image_uri = (
            f"{TARGET_APP_CLOUD_RUN_REGION}-docker.pkg.dev/{GCP_PROJECT_ID}/"
            f"{INFRA_DEFAULT_IMAGE_REPO}/{INFRA_DEFAULT_IMAGE_NAME}:latest"
        )
    else:
        final_image_uri = image_uri_to_deploy

    print("⚙️ Executing Terraform apply operation...")
    apply_report = run_terraform_apply(
        new_service_name=new_service_name,
        deployment_image_uri=final_image_uri,
        region=region
    )

    if apply_report.get("status") not in ["SUCCESS", "SUCCESS_NO_LOGS"]:
        print(f"❌ Terraform apply failed: {apply_report.get('error_message')}")
        return f"❌ Terraform apply FAILED. Reason: {apply_report.get('error_message')}"

    print("✅ Terraform apply completed successfully!")
    
    # Use the AI summary and parsed message from the infra agent
    ai_summary = apply_report.get("ai_summary", "")
    parsed_message = apply_report.get("message", "")
    log_url = apply_report.get("log_url", "")
    build_id = apply_report.get("build_id", "")
    log_retrieved = apply_report.get("log_retrieved", False)
    
    response_parts = [
        f"🚀 Terraform apply completed successfully for service '{new_service_name}'!",
        f"\n📋 Apply Summary: {parsed_message}"
    ]
    
    if ai_summary and ai_summary != "Gemini summarization not available.":
        response_parts.append(f"\n🤖 AI Analysis: {ai_summary}")
    
    if log_retrieved:
        logs_bucket = apply_report.get("logs_bucket", "")
        log_path = apply_report.get("log_path", "")
        response_parts.append(f"\n📁 Logs saved to: gs://{logs_bucket}/{log_path}")
    
    response_parts.extend([
        f"\n🔗 Build Details: {log_url}",
        f"\n🔧 Build ID: {build_id}"
    ])
    
    # Extract service URL from the parsed message if available
    if "New service URL:" in parsed_message:
        service_url = parsed_message.split("New service URL: ")[-1].strip()
        response_parts.append(f"\n🌐 Service URL: {service_url}")
        response_parts.append(f"\n✅ Your new service '{new_service_name}' is now live and accessible!")
    
    return "".join(response_parts)

# --- MOA Tool Definitions ---
def execute_smart_deploy_workflow(
    target_repository_name: str,
    target_branch_name: str
) -> str:
    """
    Orchestrates the full CI/CD/Sec pipeline: SCA -> BTA -> Security -> DA.
    """
    print(f"🚀 Starting smart deployment workflow for '{target_repository_name}' on branch '{target_branch_name}'...")
    print("📊 This process includes: Source Control → Build & Test → Security Scan → Deployment → Health Check")
    
    logging.info(f"MOA Tool (Smart Deploy): Initiating for repo '{target_repository_name}' on branch '{target_branch_name}'.")
    final_summary = []

    # Step 1: Source Control
    print("🔍 Step 1/5: Retrieving latest commit information...")
    logging.info("MOA Tool (Smart Deploy): [Step 1/5] Calling SCA logic...")
    sca_report = get_latest_commit_sha(repo_full_name=TARGET_GITHUB_REPO_FULL_NAME, branch_name=target_branch_name)
    final_summary.append(f"1. SCA Report: {sca_report.get('message', sca_report.get('error_message'))}")
    if sca_report.get("status") != "SUCCESS":
        print("❌ Source control check failed!")
        return "\n".join(final_summary)
    commit_sha = sca_report.get("commit_sha")
    print(f"✅ Source control check completed. Latest commit: {commit_sha[:8]}...")

    # Step 2: Build & Test
    print("🔨 Step 2/5: Starting build and test process...")
    logging.info("MOA Tool (Smart Deploy): [Step 2/5] Calling BTA logic...")
    bta_report = trigger_build_and_monitor(
        trigger_id=TARGET_APP_TRIGGER_ID, project_id=GCP_PROJECT_ID,
        repo_name=TARGET_GITHUB_REPO_FULL_NAME.split('/')[-1], branch_name=target_branch_name, commit_sha=commit_sha
    )
    final_summary.append(f"2. BTA Report: {bta_report.get('message', bta_report.get('error_message'))}")
    test_summary = bta_report.get("test_results", {}).get("failure_summary", "Tests not processed.")
    final_summary.append(f"   Test Status: {test_summary}")
    if bta_report.get("status") != "SUCCESS":
        print("❌ Build and test process failed!")
        return "\n".join(final_summary)
    print("✅ Build and test completed successfully!")

    # MODIFIED: Step 3 - Security Scan
    print("🔐 Step 3/5: Running security vulnerability scan...")
    logging.info("MOA Tool (Smart Deploy): [Step 3/5] Calling Security Agent logic...")
    image_digest = None
    image_base_name = None
    bta_details = bta_report.get("details")
    
    if bta_details and bta_details.get("results") and bta_details["results"].get("images"):
        first_image_info = bta_details["results"]["images"][0]
        image_digest = first_image_info.get("digest")
        full_image_name_with_tag = first_image_info.get("name")
        if full_image_name_with_tag:
            image_base_name = full_image_name_with_tag.split(':')[0]

    if image_base_name and image_digest:
        image_uri_with_digest = f"{image_base_name}@{image_digest}"
        print(f"🔍 Scanning image: {image_uri_with_digest[:50]}...")
        logging.info(f"MOA Tool (Smart Deploy): Scanning image '{image_uri_with_digest}'...")
        
        scan_results = get_vulnerability_scan_results(image_uri_with_digest=image_uri_with_digest)
        
        if scan_results.get("status") != "SUCCESS":
            print("❌ Security scan failed!")
            summary = f"Security Scan Report: FAILED to get scan results. Reason: {scan_results.get('error_message')}"
            final_summary.append(f"3. {summary}")
            final_summary.append("Deployment HALTED due to security scan error.")
            return "\n".join(final_summary)
            
        summary = summarize_vulnerabilities_with_gemini(scan_results=scan_results)
        final_summary.append(f"3. {summary}")

        if "CRITICAL" in summary.upper():
            print("🚨 Critical vulnerabilities found! Deployment halted.")
            final_summary.append("Deployment HALTED due to CRITICAL vulnerabilities found.")
            return "\n".join(final_summary)
        print("✅ Security scan completed - no critical vulnerabilities found!")
    else:
        print("⚠️ Security scan skipped - could not determine image URI")
        final_summary.append("3. Security Scan Report: SKIPPED - Could not determine image URI with digest from BTA report.")

    # Step 4: Deployment
    print("🚀 Step 4/5: Deploying to Cloud Run...")
    logging.info("MOA Tool (Smart Deploy): [Step 4/5] Calling DA logic...")
    image_uri_commit = bta_report.get("image_uri_commit")
    da_report = deploy_to_cloud_run(
        project_id=GCP_PROJECT_ID, region=TARGET_APP_CLOUD_RUN_REGION,
        service_name=TARGET_APP_CLOUD_RUN_SERVICE_NAME, image_uri=image_uri_commit
    )
    final_summary.append(f"4. Deployment: {da_report.get('message', da_report.get('error_message'))}")
    if da_report.get("status") != "SUCCESS":
        print("❌ Deployment failed!")
        return "\n".join(final_summary)
    print("✅ Deployment completed successfully!")

    # MODIFIED: Step 5 - Post-Deployment Health Check & Potential Rollback
    print("🏥 Step 5/5: Running post-deployment health check...")
    logging.info("MOA Tool (Smart Deploy): [Step 5/5] Performing post-deployment health check...")
    health_check_raw_data = execute_health_check_workflow(
        service_id=TARGET_APP_CLOUD_RUN_SERVICE_NAME,
        location=TARGET_APP_CLOUD_RUN_REGION,
        time_window_minutes=5 # Check a short window right after deployment
    )
    
    # Simple check for health issues based on raw data.
    # A more advanced check could use another LLM call to interpret the health data.
    if "Error Count (4xx+5xx): 0" not in health_check_raw_data: # Simple heuristic for errors
        print("⚠️ Health check detected issues - initiating rollback...")
        final_summary.append("5. Post-Deployment Health Check: FAILED - Errors detected after deployment.")
        logging.warning("Deployment appears unhealthy, initiating automated rollback.")
        
        rollback_summary = execute_rollback_workflow(
            service_id=TARGET_APP_CLOUD_RUN_SERVICE_NAME,
            location=TARGET_APP_CLOUD_RUN_REGION
        )
        final_summary.append(f"   Rollback Action: {rollback_summary}")
    else:
        print("✅ Health check passed - deployment is healthy!")
        final_summary.append("5. Post-Deployment Health Check: PASSED - No immediate issues detected.")
        
    print("🎉 Smart deployment workflow completed!")
    return "\n".join(final_summary)


def execute_health_check_workflow(
    service_id: str, location: str, time_window_minutes: int = 15, max_log_entries: int = 5
) -> str:
    print(f"🏥 Starting health check for service '{service_id}' in '{location}'...")
    print("📊 Gathering metrics and logs...")
    
    logging.info(f"MOA Tool (Health Check): Initiating for service '{service_id}' in '{location}'.")
    metrics_report = get_cloud_run_metrics(
        project_id=GCP_PROJECT_ID, service_id=service_id, location=location,
        time_window_minutes=time_window_minutes
    )
    logs_report = get_cloud_run_logs(
        project_id=GCP_PROJECT_ID, service_id=service_id, location=location,
        time_window_minutes=time_window_minutes, max_entries=max_log_entries
    )
    
    print("📋 Generating health report...")
    raw_data_report_string = generate_health_report(
        service_id=service_id, metrics_report=metrics_report, logs_report=logs_report
    )
    
    print("✅ Health check completed!")
    return raw_data_report_string

def execute_finops_report_workflow(
    days_ago: int = 7
) -> str:
    print(f"💰 Starting cost analysis for the last {days_ago} days...")
    print("📊 Gathering billing data...")
    
    logging.info(f"MOA Tool (FinOps): Initiating cost report for the last {days_ago} days.")
    total_cost_report = get_total_project_cost(days_ago=days_ago)
    cost_by_service_report = get_cost_by_service(days_ago=days_ago)
    
    print("📋 Generating cost report...")
    report_parts = [f"FinOps Report Data (last {days_ago} days):\n"]
    if total_cost_report.get("status") == "SUCCESS":
        report_parts.append(f"Total Cost: {total_cost_report.get('total_cost', 'N/A')}")
    else:
        report_parts.append(f"Total Cost: Error - {total_cost_report.get('error_message')}")
    if cost_by_service_report.get("status") == "SUCCESS":
        cost_breakdown = cost_by_service_report.get('cost_breakdown', [])
        report_parts.append("\nTop Services by Cost:")
        if cost_breakdown:
            for service in cost_breakdown:
                report_parts.append(f"  - {service.get('service_name')}: {service.get('total_cost')}")
        else:
            report_parts.append("  - No cost data found for services.")
    else:
        report_parts.append(f"\nTop Services by Cost: Error - {cost_by_service_report.get('error_message')}")
    
    print("✅ Cost analysis completed!")
    return "\n".join(report_parts)

def execute_rollback_workflow(
    service_id: str, location: str
) -> str:
    print(f"🔄 Starting rollback process for service '{service_id}' in '{location}'...")
    print("📋 Finding previous stable revision...")
    
    logging.info(f"MOA Tool (Rollback): Initiating for service '{service_id}' in '{location}'.")
    
    # Get previous stable revision
    revision_report = get_previous_stable_revision(
        project_id=GCP_PROJECT_ID, service_id=service_id, location=location
    )
    
    if revision_report.get("status") != "SUCCESS":
        error_msg = f"Failed to get previous stable revision: {revision_report.get('error_message')}"
        print(f"❌ {error_msg}")
        return error_msg
    
    previous_revision = revision_report.get("previous_revision")
    if not previous_revision:
        error_msg = "No previous stable revision found for rollback."
        print(f"❌ {error_msg}")
        return error_msg
    
    print(f"📦 Rolling back to revision: {previous_revision}")
    
    # Redirect traffic to previous revision
    redirect_report = redirect_traffic_to_revision(
        project_id=GCP_PROJECT_ID, service_id=service_id, location=location, revision_name=previous_revision
    )
    
    if redirect_report.get("status") == "SUCCESS":
        success_msg = f"Successfully rolled back to revision {previous_revision}"
        print(f"✅ {success_msg}")
        return success_msg
    else:
        error_msg = f"Rollback failed: {redirect_report.get('error_message')}"
        print(f"❌ {error_msg}")
        return error_msg


# --- ADK Agent Definition for MOA ---
root_agent = LlmAgent(
    name="geminiflow_master_orchestrator_agent",
    model="gemini-2.0-flash",
    description=(
        "The Master Orchestrator Agent for the GeminiFlow DevSecOps Co-Pilot."
    ),
     instruction=(
        "You are the Master Orchestrator for a DevSecOps system called GeminiFlow. "
        "You have specialized sub-agents. Your primary roles are to manage secure deployments, provide health checks, and provision new infrastructure. "
        "\n1. For DEPLOYMENTS: When a user asks to deploy an application, this includes a security scan. Use the 'execute_smart_deploy_workflow' tool. "
        "\n2. For HEALTH CHECKS: When a user asks for the health or status of a service, use the 'execute_health_check_workflow' tool and summarize the raw data it returns."
        "\n3. For INFRASTRUCTURE PROVISIONING: This is a two-step process. "
        "  a. First, when a user asks to 'plan' or 'provision' a new environment (e.g., 'plan a new staging service named staging-v2'), "
        "     identify the new service name and the image to deploy. Then, you MUST use the 'plan_new_environment' tool. "
        "     Present the plan summary with AI analysis to the user and tell them to give approval to apply it."
        "  b. Second, when the user gives approval (e.g., 'yes, apply the plan for staging-v2'), "
        "     you MUST use the 'apply_new_environment' tool with the same parameters to create the infrastructure."
        "\n4. For COST ANALYSIS: When users ask about costs or spending, use 'execute_finops_report_workflow'."
        "\n5. For ROLLBACKS: When users request a rollback, use 'execute_rollback_workflow'."
    ),
    tools=[
        execute_smart_deploy_workflow,
        execute_health_check_workflow,
        execute_finops_report_workflow,
        execute_rollback_workflow,
        plan_new_environment,
        apply_new_environment
    ],
    sub_agents=[sca_agent, bta_agent, da_agent, mda_agent, finops_agent, secops_agent, rollback_agent, infra_agent]
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
        print("   User: deploy gemini-flow-hello-world from main")
        print("   User: what is the health of geminiflow-hello-world-svc in us-central1")
        print("   User: how much have we spent in the last 14 days")
        print("   User: plan a new staging service named staging-v2")
        print("   User: apply the plan for staging-v2")
        print("   User: what are the security vulnerabilities in us-central1-docker.pkg.dev/geminiflow-461207/gemini-flow-apps/gemini-flow-hello-world@sha256:...")