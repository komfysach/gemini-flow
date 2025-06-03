# bta_agent.py
# Agent Development Kit (ADK) Build & Test Agent (BTA) for GeminiFlow

import os
import time
import logging
from google.adk.agents import Agent
from google.cloud.devtools import cloudbuild_v1
from google.protobuf.json_format import MessageToDict
from dotenv import load_dotenv
load_dotenv()

# Configure basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Configuration ---
GCP_PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT")
DEFAULT_TRIGGER_ID = "deploy-hello-world-app" 
DEFAULT_REPO_NAME = "gemini-flow-hello-world"
ARTIFACT_REGISTRY_LOCATION = os.getenv("ARTIFACT_REGISTRY_LOCATION", "us-central1")
ARTIFACT_REGISTRY_REPO = os.getenv("ARTIFACT_REGISTRY_REPO", "gemini-flow-apps")
IMAGE_NAME = "gemini-flow-hello-world"


# --- BTA Tools ---

def trigger_build_and_monitor(
    trigger_id: str,
    project_id: str,
    repo_name: str,
    branch_name: str,
    commit_sha: str = None  
) -> dict:
    """
    Triggers a Cloud Build job using a specified trigger and monitors its completion.

    Args:
        trigger_id (str): The ID of the Cloud Build trigger.
        project_id (str): The Google Cloud Project ID.
        repo_name (str): The name of the repository associated with the trigger.
        branch_name (str): The name of the branch to build.
        commit_sha (str, optional): The specific commit SHA to build.
                                    If None, the trigger typically uses the latest commit on the branch.

    Returns:
        dict: A dictionary containing the build status, build ID, any error messages,
              and the constructed image URIs if successful.
              Example success:
              {
                  "status": "SUCCESS",
                  "build_id": "build-id-xyz",
                  "image_uri_commit": "location-docker.pkg.dev/project/repo/image:commitsha",
                  "image_uri_latest": "location-docker.pkg.dev/project/repo/image:latest",
                  "message": "Build completed successfully."
              }
              Example failure:
              {
                  "status": "FAILURE", # or TIMEOUT, CANCELLED, etc.
                  "build_id": "build-id-abc",
                  "error_message": "Build step X failed.",
                  "details": "{...full build object...}"
              }
    """
    if not project_id:
        return {"status": "ERROR", "error_message": "GCP_PROJECT_ID is not set."}
    if not trigger_id:
        return {"status": "ERROR", "error_message": "Trigger ID is not provided."}

    logging.info(f"Attempting to trigger Cloud Build: project='{project_id}', trigger='{trigger_id}', branch='{branch_name}'")

    try:
        client = cloudbuild_v1.CloudBuildClient()

        # Define the source to build.
        # The trigger itself usually defines the repo, but you can override/specify branch/commit.
        repo_source = cloudbuild_v1.types.RepoSource()
        repo_source.project_id = project_id
        repo_source.repo_name = repo_name 
        repo_source.branch_name = branch_name
        if commit_sha:
            repo_source.commit_sha = commit_sha

        # Run the build trigger
        logging.info(f"Running trigger '{trigger_id}' for branch '{branch_name}'" + (f" and commit '{commit_sha}'" if commit_sha else ""))
        operation = client.run_build_trigger(
            project_id=project_id,
            trigger_id=trigger_id,
            source=repo_source # Pass the RepoSource object
        )

        logging.info(f"Build triggered. Operation name: {operation.metadata.build.id}. Waiting for completion...")

        # The operation.result() call will block until the build is complete.
        # You can specify a timeout for operation.result(timeout=SECONDS)
        # The `operation.metadata` field contains the Build object.
        build_result = operation.result(timeout=1200) # Wait up to 20 minutes, matching cloudbuild.yaml timeout

        build_id = build_result.id
        build_status_str = cloudbuild_v1.Build.Status(build_result.status).name
        logging.info(f"Build {build_id} completed with status: {build_status_str}")

        if build_status_str in ["SUCCESS"]:
            # Resolve the actual commit SHA used by the build if not explicitly passed
            # This is important if the trigger built the "latest" on a branch.
            # The build_result.source_provenance.resolved_repo_source.commit_sha should have it.
            # Or, if you passed commit_sha, use that.
            final_commit_sha = commit_sha
            if hasattr(build_result, 'source_provenance') and \
               hasattr(build_result.source_provenance, 'resolved_repo_source') and \
               build_result.source_provenance.resolved_repo_source.commit_sha:
                final_commit_sha = build_result.source_provenance.resolved_repo_source.commit_sha
            elif not final_commit_sha and hasattr(build_result, 'substitutions') and 'COMMIT_SHA' in build_result.substitutions:
                 final_commit_sha = build_result.substitutions['COMMIT_SHA']


            if not final_commit_sha:
                logging.warning(f"Could not determine the exact commit SHA from build result for build {build_id}. Image URI might be incomplete.")
                # Fallback or error if commit_sha is crucial and not found
                return {
                    "status": "WARNING_SUCCESS", # Build succeeded but SHA missing for URI
                    "build_id": build_id,
                    "message": "Build succeeded, but commit SHA for image tagging could not be determined.",
                    "details": MessageToDict(build_result._pb)
                }


            image_uri_commit = f"{ARTIFACT_REGISTRY_LOCATION}-docker.pkg.dev/{project_id}/{ARTIFACT_REGISTRY_REPO}/{IMAGE_NAME}:{final_commit_sha}"
            image_uri_latest = f"{ARTIFACT_REGISTRY_LOCATION}-docker.pkg.dev/{project_id}/{ARTIFACT_REGISTRY_REPO}/{IMAGE_NAME}:latest"

            return {
                "status": "SUCCESS",
                "build_id": build_id,
                "image_uri_commit": image_uri_commit,
                "image_uri_latest": image_uri_latest,
                "message": "Build completed successfully and image URIs constructed."
            }
        else:
            log_url = build_result.log_url
            error_message = f"Build {build_id} failed with status {build_status_str}. Logs: {log_url}"
            logging.error(error_message)
            # You might want to include more details from build_result if needed
            return {
                "status": build_status_str, # e.g., FAILURE, TIMEOUT, CANCELLED
                "build_id": build_id,
                "error_message": error_message,
                "details": MessageToDict(build_result._pb) # Full build object for debugging
            }

    except Exception as e:
        error_msg = f"An error occurred while triggering or monitoring the build: {str(e)}"
        logging.exception(error_msg) # Logs the full traceback
        return {"status": "ERROR", "error_message": error_msg}

# --- ADK Agent Definition ---
# This BTA agent is fairly simple and its primary logic is within the tool.
# It doesn't need its own LLM for decision-making for these tasks.
# The MOA would call its tools.

bta_agent = Agent(
    name="geminiflow_build_test_agent",
    description="An agent responsible for triggering, monitoring, and reporting on application build and test pipelines.",
    instruction=(
        "You are a Build and Test Agent. You receive requests to trigger builds for specific applications, "
        "monitor their progress, and report back the status and any resulting artifacts (like image URIs)."
    ),
    tools=[trigger_build_and_monitor],
    # No LLM model needed for this agent if its tools are deterministic.
    # If it needed to interpret complex test results with an LLM, you'd add:
    # model="gemini-2.0-flash",
)

# --- Local Testing Example ---
if __name__ == "__main__":
    # Before running:
    # 1. Ensure you've authenticated gcloud locally: `gcloud auth application-default login`
    # 2. Set the GOOGLE_APPLICATION_CREDENTIALS environment variable to the path of your
    #    build-test-agent-bca@... service account JSON key file.
    #    e.g., export GOOGLE_APPLICATION_CREDENTIALS="/path/to/your/bca-key.json"
    # 3. Set the GOOGLE_CLOUD_PROJECT environment variable to your GCP Project ID.
    #    e.g., export GOOGLE_CLOUD_PROJECT="geminiflow-461207"
    # 4. Replace DEFAULT_TRIGGER_ID with your actual trigger ID.
    # 5. Ensure ARTIFACT_REGISTRY_LOCATION and ARTIFACT_REGISTRY_REPO are set if not using defaults.

    if not GCP_PROJECT_ID:
        print("Error: GOOGLE_CLOUD_PROJECT environment variable is not set.")
    elif DEFAULT_TRIGGER_ID == "38fc336d-3df5-49ea-bae7-2c4ae40ef5d6":
        print("Error: Please replace DEFAULT_TRIGGER_ID with your actual Cloud Build trigger ID in the script.")
    else:
        print(f"--- Testing BTA: Triggering build for gemini-flow-hello-world on main branch ---")
        # For testing, we might not have a specific commit_sha from SCA yet,
        # so we'll let the trigger use the latest on the 'main' branch.
        # The SCA would normally provide the commit_sha.
        # For now, let's simulate a scenario where MOA asks to build the 'main' branch.
        # The `trigger_build_and_monitor` function will try to get the commit_sha from the build result.

        # You might need to provide a commit_sha that actually exists on the branch
        # if your trigger is not set to just build the tip of the branch.
        # For this test, let's assume the trigger builds the latest of 'main'.
        # The SCA would typically provide the commit_sha to build.
        # For an initial test, you can get a recent commit SHA from your GitHub repo for 'main'
        # and pass it here, or let the trigger pick the latest.
        test_commit_sha = None # Or a specific commit SHA string if needed for your trigger setup

        build_report = trigger_build_and_monitor(
            trigger_id=DEFAULT_TRIGGER_ID,
            project_id=GCP_PROJECT_ID,
            repo_name=DEFAULT_REPO_NAME, 
            branch_name="main", 
            commit_sha=test_commit_sha
        )

        print("\n--- Build Report ---")
        if build_report:
            for key, value in build_report.items():
                if key == "details" and isinstance(value, dict): # Don't print huge details dict
                    print(f"  {key}: {{...build details object...}}")
                else:
                    print(f"  {key}: {value}")
        else:
            print("  No report generated.")

        if build_report and build_report.get("status") == "SUCCESS":
            print("\nBTA Test: SUCCESS - Build reported success and image URIs generated.")
        else:
            print("\nBTA Test: FAILED or ERRORED - Check messages above.")

