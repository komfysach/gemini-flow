# bta_agent.py

import os
import logging
import json
from google.adk.agents import Agent # Or LlmAgent if BTA directly uses an LLM for complex tasks
from google.cloud.devtools import cloudbuild_v1
from google.cloud import storage
from google.protobuf.json_format import MessageToDict
import google.generativeai as genai # For calling Gemini API directly
from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


# --- Configuration ---
GCP_PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT")
DEFAULT_TRIGGER_ID = os.getenv("TARGET_APP_TRIGGER_ID", "your-geminiflow-hello-world-trigger-id")
DEFAULT_REPO_NAME = os.getenv("TARGET_GITHUB_REPO_NAME", "gemini-flow-hello-world")
ARTIFACT_REGISTRY_LOCATION = os.getenv("ARTIFACT_REGISTRY_LOCATION", "us-central1")
ARTIFACT_REGISTRY_REPO = os.getenv("ARTIFACT_REGISTRY_REPO", "gemini-flow-apps")
IMAGE_NAME = "gemini-flow-hello-world"
TEST_RESULTS_BUCKET_NAME = os.getenv("TEST_RESULTS_BUCKET_NAME", "your-project-id-geminiflow-build-artifacts") # REPLACE
GEMINI_MODEL_NAME = "gemini-2.0-flash"
VERTEX_AI_LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")

def _download_gcs_artifact(bucket_name: str, object_name: str) -> str | None:
    try:
        storage_client = storage.Client(project=GCP_PROJECT_ID)
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(object_name)
        logging.info(f"BTA: Checking for artifact in GCS: bucket={bucket_name}, object={object_name}")
        if not blob.exists():
            logging.warning(f"BTA: Artifact not found in GCS: gs://{bucket_name}/{object_name}")
            return None
        logging.info(f"BTA: Downloading artifact gs://{bucket_name}/{object_name}")
        return blob.download_as_text()
    except Exception as e:
        logging.error(f"BTA: Failed to download GCS artifact gs://{bucket_name}/{object_name}: {e}")
        return None

def _parse_go_test_json(json_content: str) -> dict:
    """Parses the line-by-line JSON output from 'go test -json'."""
    results = {"tests": 0, "failures": 0, "skipped": 0, "failure_details": []}
    if not json_content:
        return results

    test_outputs = {}
    test_events = []
    
    # First pass: decode all lines into a list of event dictionaries
    for line in json_content.strip().split('\n'):
        try:
            event = json.loads(line)
            test_events.append(event)
        except json.JSONDecodeError:
            logging.warning(f"BTA: Skipping non-JSON line in test output: {line}")
            continue

    # Second pass: process the events to count tests and collect outputs
    for event in test_events:
        action = event.get("Action")
        test_name = event.get("Test")

        # Only process events associated with a specific test
        if not test_name:
            continue

        if action == "run":
            results["tests"] += 1
            test_outputs[test_name] = [] # Initialize output buffer for this test

        elif action == "output" and test_name in test_outputs:
            test_outputs[test_name].append(event.get("Output", ""))
        
        elif action == "skip":
            results["skipped"] += 1

    # Third pass: Now that all outputs are collected, create failure details for any failed tests
    failed_tests = {event.get("Test") for event in test_events if event.get("Action") == "fail" and event.get("Test")}
    
    for test_name in failed_tests:
        failure_detail = {
            "test_name": test_name,
            "details": "".join(test_outputs.get(test_name, ["No output captured for this test."])).strip()
        }
        results["failure_details"].append(failure_detail)

    results['failures'] = len(results['failure_details'])
    logging.info(f"BTA: Parsed test results: Total={results['tests']}, Failures={results['failures']}")
    return results

def _summarize_test_failures_with_gemini(failure_details: list) -> str:
    if not failure_details:
        return "No failures to summarize."
    if not GCP_PROJECT_ID or not VERTEX_AI_LOCATION or 'genai' not in globals() or not hasattr(genai,'GenerativeModel'):
        logging.warning("BTA: Gemini client not configured, cannot summarize failures.")
        return "Gemini summarization not available. Raw failure details provided."
    try:
        model = genai.GenerativeModel(GEMINI_MODEL_NAME)
        prompt = "You are a helpful assistant. Summarize the following test failures from a CI build. Be concise and highlight the main reasons for failures if possible:\n\n"
        for i, f in enumerate(failure_details):
            prompt += f"Failure {i+1}:\n"
            prompt += f"  Test: {f.get('class_name', '')}.{f.get('test_name', '')}\n"
            prompt += f"  Message: {f.get('message', '')}\n"
            prompt += f"  Details: {f.get('details', '')[:500]}\n\n" 
        logging.info("BTA: Sending test failures to Gemini for summarization...")
        response = model.generate_content(prompt)
        summary = response.text
        logging.info("BTA: Gemini summarization successful.")
        return summary
    except Exception as e:
        logging.error(f"BTA: Error during Gemini summarization: {e}")
        return f"Could not summarize failures due to an error: {e}. Raw details: {str(failure_details)}"


def trigger_build_and_monitor( 
    trigger_id: str,
    project_id: str,
    repo_name: str, 
    branch_name: str,
    commit_sha: str = None
) -> dict:
    if not project_id: 
        project_id = GCP_PROJECT_ID
    if not project_id:
        return {"status": "ERROR", "error_message": "GCP_PROJECT_ID is not set."}

    test_results_summary = {
        "test_status": "NOT_INITIALIZED",
        "tests_run": 0,
        "tests_failed": 0,
        "tests_errors": 0,
        "failure_summary": "Test processing not reached or an early error occurred."
    }

    logging.info(f"BTA: Triggering Cloud Build: project='{project_id}', trigger='{trigger_id}', branch='{branch_name}'")
    client = cloudbuild_v1.CloudBuildClient()

    
    source_to_build_dict = {
        "repo_name": repo_name,
        "substitutions": {}, 
    }
    
    # Set the revision (branch or commit) on the source dictionary
    if commit_sha:
        source_to_build_dict["commit_sha"] = commit_sha
    else:
        source_to_build_dict["branch_name"] = branch_name
    
    try:
        logging.info(f"BTA: Submitting trigger request with source as dictionary: {source_to_build_dict}")
        
        # Call the client library method using the dictionary for the 'source' parameter.
        operation = client.run_build_trigger(
            project_id=project_id,
            trigger_id=trigger_id,
            source=source_to_build_dict
        )
        
        logging.info(f"BTA: Build triggered. Operation name: {operation.metadata.build.id}. Waiting...")
        build_result = operation.result(timeout=1200) 
        
        # ... (rest of the function for processing results remains the same) ...
        build_id = build_result.id
        build_status_str = cloudbuild_v1.Build.Status(build_result.status).name
        logging.info(f"BTA: Build {build_id} completed with status: {build_status_str}")
        
        final_commit_sha_for_artifacts = commit_sha
        if not final_commit_sha_for_artifacts and build_result.source_provenance and \
           build_result.source_provenance.resolved_repo_source and \
           build_result.source_provenance.resolved_repo_source.commit_sha:
            final_commit_sha_for_artifacts = build_result.source_provenance.resolved_repo_source.commit_sha
        elif not final_commit_sha_for_artifacts and build_result.substitutions and 'COMMIT_SHA' in build_result.substitutions:
            final_commit_sha_for_artifacts = build_result.substitutions['COMMIT_SHA']
        
        if final_commit_sha_for_artifacts:
            test_artifact_object_name = f"test-results/{final_commit_sha_for_artifacts}/test_results.json"
            logging.info(f"BTA: Downloading test artifact: gs://{TEST_RESULTS_BUCKET_NAME}/{test_artifact_object_name}")
            json_content = _download_gcs_artifact(TEST_RESULTS_BUCKET_NAME, test_artifact_object_name)

            if json_content:
                parsed_results = _parse_go_test_json(json_content)
                test_results_summary["tests_run"] = parsed_results.get("tests", 0)
                test_results_summary["tests_failed"] = parsed_results.get("failures", 0)
                test_results_summary["tests_skipped"] = parsed_results.get("skipped", 0)
                if parsed_results.get("failures", 0) > 0:
                    test_results_summary["test_status"] = "FAILED"
                    test_results_summary["failure_summary"] = _summarize_test_failures_with_gemini(parsed_results.get("failure_details", []))
                elif parsed_results.get("tests", 0) > 0:
                    test_results_summary["test_status"] = "PASSED"
                    test_results_summary["failure_summary"] = "All tests passed."
                else:
                    test_results_summary["test_status"] = "NO_TESTS_FOUND_IN_REPORT"
            else:
                test_results_summary["test_status"] = "RESULTS_FILE_NOT_FOUND"
                test_results_summary["failure_summary"] = "Test results JSON file not found in artifacts."
        else:
            logging.warning("BTA: Could not determine commit SHA for fetching test artifacts.")
            test_results_summary["failure_summary"] = "Could not determine commit SHA for fetching test artifacts."

        if build_status_str == "SUCCESS":
            final_commit_sha_for_image = final_commit_sha_for_artifacts 
            if not final_commit_sha_for_image:
                 return {
                    "status": "WARNING_SUCCESS", 
                    "build_id": build_id,
                    "message": "Build succeeded, but commit SHA for image tagging could not be determined.",
                    "details": MessageToDict(build_result._pb),
                    "test_results": test_results_summary
                }
            image_uri_commit = f"{ARTIFACT_REGISTRY_LOCATION}-docker.pkg.dev/{project_id}/{ARTIFACT_REGISTRY_REPO}/{IMAGE_NAME}:{final_commit_sha_for_image}"
            image_uri_latest = f"{ARTIFACT_REGISTRY_LOCATION}-docker.pkg.dev/{project_id}/{ARTIFACT_REGISTRY_REPO}/{IMAGE_NAME}:latest"
            
            return {
                "status": "SUCCESS",
                "build_id": build_id,
                "image_uri_commit": image_uri_commit,
                "image_uri_latest": image_uri_latest,
                "message": "Build completed successfully.",
                "test_results": test_results_summary
            }
        else: 
            log_url = build_result.log_url
            error_message = f"Build {build_id} failed with status {build_status_str}. Logs: {log_url}"
            logging.error(error_message)
            return {
                "status": build_status_str,
                "build_id": build_id,
                "error_message": error_message,
                "details": MessageToDict(build_result._pb),
                "test_results": test_results_summary 
            }

    except Exception as e:
        error_msg = f"BTA: An error occurred while triggering or monitoring the build: {str(e)}"
        logging.exception(error_msg)
        return {"status": "ERROR", "error_message": error_msg, "test_results": test_results_summary}


# --- ADK Agent Definition for BTA ---
bta_agent = Agent( 
    name="geminiflow_build_test_agent_enhanced",
    description="Agent to trigger builds, monitor, and analyze test results with Gemini.",
    instruction="You manage build and test pipelines, including test result analysis.",
    tools=[trigger_build_and_monitor],
)

# --- Local Testing Example for BTA ---
if __name__ == "__main__":
    if not GCP_PROJECT_ID or not os.getenv("TARGET_APP_TRIGGER_ID") or not os.getenv("TEST_RESULTS_BUCKET_NAME") or not os.getenv("GOOGLE_CLOUD_LOCATION"):
        print("Error: Ensure GOOGLE_CLOUD_PROJECT, TARGET_APP_TRIGGER_ID, TEST_RESULTS_BUCKET_NAME, and GOOGLE_CLOUD_LOCATION env vars are set.")
    else:
        print(f"--- Testing BTA (Enhanced): Triggering build for {DEFAULT_REPO_NAME} on main branch ---")
        
        test_commit_sha = None 
        branch = "main" 

        build_report = trigger_build_and_monitor(
            trigger_id=os.getenv("TARGET_APP_TRIGGER_ID"),
            project_id=GCP_PROJECT_ID,
            repo_name=DEFAULT_REPO_NAME, 
            branch_name=branch, 
            commit_sha=test_commit_sha
        )
        print("\n--- Enhanced Build Report ---")
        import json
        print(json.dumps(build_report, indent=2))

        if build_report and build_report.get("status") == "SUCCESS":
            print("\nBTA Enhanced Test: SUCCESS - Build reported success.")
            if build_report.get("test_results"):
                print(f"Test Status: {build_report['test_results'].get('test_status')}")
                if build_report['test_results'].get('tests_failed',0) > 0 or build_report['test_results'].get('tests_errors',0) > 0 :
                    print(f"Failure Summary from Gemini: {build_report['test_results'].get('failure_summary')}")
        else:
            print("\nBTA Enhanced Test: FAILED or ERRORED - Check messages above.")
            if build_report.get("test_results"):
                 print(f"Test Status (on failure/error): {build_report['test_results'].get('test_status')}")
                 print(f"Failure Info: {build_report['test_results'].get('failure_summary')}")

