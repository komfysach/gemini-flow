# rollback_agent.py
# Agent Development Kit (ADK) Rollback Agent for GeminiFlow

import os
import logging
from google.adk.agents import Agent
from google.cloud import run_v2
from google.api_core import exceptions as api_exceptions
from google.protobuf import field_mask_pb2
from dotenv import load_dotenv
load_dotenv()

# Configure basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Rollback Agent Configuration ---
# For local testing, ensure GOOGLE_APPLICATION_CREDENTIALS is set to the path of
# the geminiflow-rollback-sa@... service account key file.
# This SA needs "Cloud Run Admin" to get and update services.
GCP_PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT")
DEFAULT_CLOUD_RUN_REGION = os.getenv("TARGET_APP_CLOUD_RUN_REGION", "us-central1")
DEFAULT_SERVICE_NAME = os.getenv("TARGET_APP_CLOUD_RUN_SERVICE_NAME", "geminiflow-hello-world-svc")


# --- Rollback Agent Tools ---

def get_previous_stable_revision(
    project_id: str,
    location: str,
    service_id: str
) -> dict:
    """
    Finds the name of the last known stable revision for a Cloud Run service.
    It identifies the latest revision currently serving traffic and then finds the
    second-to-last revision from the list of all revisions, assuming it was the
    previous stable one.

    Args:
        project_id (str): The Google Cloud Project ID.
        location (str): The Cloud Run service location/region.
        service_id (str): The Cloud Run service ID.

    Returns:
        dict: A dictionary containing the status and the name of the previous stable revision.
    """
    if not all([project_id, location, service_id]):
        return {"status": "ERROR", "error_message": "Project ID, Location, and Service ID are required."}

    logging.info(f"Rollback Agent: Getting previous stable revision for service '{service_id}'.")
    client = run_v2.RevisionsClient()
    parent = f"projects/{project_id}/locations/{location}/services/{service_id}"

    try:
        revisions_list = client.list_revisions(parent=parent)
        revisions = sorted(
            [rev for rev in revisions_list],
            key=lambda r: r.create_time,
            reverse=True
        )

        if len(revisions) < 2:
            msg = "Fewer than two revisions exist; cannot determine a previous stable revision to roll back to."
            logging.warning(f"Rollback Agent: {msg}")
            return {"status": "FAILURE", "error_message": msg}

        # The first revision in the sorted list (index 0) is the latest (potentially bad) one.
        # The second revision (index 1) is assumed to be the last known stable one.
        previous_stable_revision_name = revisions[1].name
        logging.info(f"Rollback Agent: Found previous stable revision: '{previous_stable_revision_name}'")
        
        return {
            "status": "SUCCESS",
            "previous_stable_revision_name": previous_stable_revision_name,
            "message": f"Identified previous stable revision '{revisions[1].name.split('/')[-1]}'."
        }

    except api_exceptions.NotFound:
        msg = f"Service '{service_id}' not found in location '{location}'."
        logging.error(f"Rollback Agent: {msg}")
        return {"status": "ERROR", "error_message": msg}
    except Exception as e:
        error_msg = f"Rollback Agent: Error getting previous stable revision: {e}"
        logging.exception(error_msg)
        return {"status": "ERROR", "error_message": error_msg}


def redirect_traffic_to_revision(
    project_id: str,
    location: str,
    service_id: str,
    revision_name: str
) -> dict:
    """
    Updates a Cloud Run service to direct 100% of traffic to a specific revision.
    This function uses a FieldMask to explicitly update only the traffic configuration,
    preventing "required field not present" errors.

    Args:
        project_id (str): The Google Cloud Project ID.
        location (str): The Cloud Run service location/region.
        service_id (str): The Cloud Run service ID.
        revision_name (str): The full name of the revision to receive 100% of traffic.

    Returns:
        dict: A dictionary containing the status of the traffic redirection.
    """
    if not all([project_id, location, service_id, revision_name]):
        return {"status": "ERROR", "error_message": "Project ID, Location, Service ID, and Revision Name are required."}

    # Extract the short name from the full revision path. This is the key fix.
    revision_short_name = revision_name.split('/')[-1]

    logging.info(f"Rollback Agent: Redirecting 100% of traffic for '{service_id}' to revision '{revision_short_name}'.")
    client = run_v2.ServicesClient()
    service_full_path = f"projects/{project_id}/locations/{location}/services/{service_id}"
    
    try:
        # STEP 1: Get the current service configuration.
        service = client.get_service(name=service_full_path)

        # STEP 2: Define the new traffic split using the SHORT revision name.
        traffic_target = run_v2.types.TrafficTarget(
            revision=revision_short_name, # Use the short name here
            percent=100,
            type_=run_v2.types.TrafficTargetAllocationType.TRAFFIC_TARGET_ALLOCATION_TYPE_REVISION
        )
        
        # STEP 3: Update the traffic attribute on the fetched service object.
        service.traffic = [traffic_target]
        
        # STEP 4: Create an update_mask to only modify the traffic field.
        update_mask = field_mask_pb2.FieldMask(paths=["traffic"])
        
        # STEP 5: Call update_service with the modified service object and the update mask.
        operation = client.update_service(
            service=service,
            update_mask=update_mask
        )
        logging.info("Rollback Agent: Waiting for traffic update to complete...")
        operation.result(timeout=300) # Wait up to 5 minutes
        
        message = f"Successfully rolled back service '{service_id}' to direct all traffic to revision '{revision_short_name}'."
        logging.info(f"Rollback Agent: {message}")
        return {"status": "SUCCESS", "message": message}

    except Exception as e:
        error_msg = f"Rollback Agent: Error redirecting traffic: {e}"
        logging.exception(error_msg)
        return {"status": "ERROR", "error_message": error_msg}
    
# --- ADK Agent Definition ---
rollback_agent = Agent(
    name="geminiflow_rollback_agent",
    description="An agent that can roll back a Cloud Run service to a previous stable revision if a deployment is found to be unhealthy.",
    instruction="You are a Rollback Agent. Your tools are used to find previous revisions and redirect traffic for incident response.",
    tools=[
        get_previous_stable_revision,
        redirect_traffic_to_revision,
    ],
)

# --- Local Testing Example ---
if __name__ == "__main__":
    # Before running:
    # 1. Install libraries: `pip install google-cloud-run python-dotenv`
    # 2. Set GOOGLE_APPLICATION_CREDENTIALS to your Rollback SA key file.
    # 3. Set GOOGLE_CLOUD_PROJECT, and ensure the target service exists.
    
    if not GCP_PROJECT_ID:
        print("Rollback Test Error: Please set the GOOGLE_CLOUD_PROJECT environment variable.")
    else:
        print(f"--- Testing Rollback Agent Tools for service: {DEFAULT_SERVICE_NAME} ---")
        
        # Step 1: Find the previous stable revision
        stable_rev_report = get_previous_stable_revision(
            project_id=GCP_PROJECT_ID,
            location=DEFAULT_CLOUD_RUN_REGION,
            service_id=DEFAULT_SERVICE_NAME
        )
        print("\n--- Previous Stable Revision Report ---")
        import json
        print(json.dumps(stable_rev_report, indent=2))

        # Step 2: If found, redirect traffic to it
        if stable_rev_report.get("status") == "SUCCESS":
            revision_to_restore = stable_rev_report.get("previous_stable_revision_name")
            print(f"\n--- Redirecting traffic to: {revision_to_restore} ---")
            
            redirect_report = redirect_traffic_to_revision(
                project_id=GCP_PROJECT_ID,
                location=DEFAULT_CLOUD_RUN_REGION,
                service_id=DEFAULT_SERVICE_NAME,
                revision_name=revision_to_restore
            )
            print("\n--- Traffic Redirection Report ---")
            print(json.dumps(redirect_report, indent=2))
        else:
            print("\nSkipping traffic redirection due to failure in finding a stable revision.")
