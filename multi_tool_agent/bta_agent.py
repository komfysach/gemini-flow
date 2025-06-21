# bta_agent.py

import os
import logging
import json
import time
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
    commit_sha: str
) -> dict:
    """
    Triggers a Cloud Build and monitors it to completion, with enhanced log capture and summarization.
    """
    print(f"🔨 Triggering build for {repo_name}:{branch_name} (commit: {commit_sha[:8]})")
    
    if not all([trigger_id, project_id, repo_name, branch_name, commit_sha]):
        return {"status": "ERROR", "error_message": "Missing required parameters for build trigger."}
    
    logging.info(f"BTA Agent: Triggering build for repo '{repo_name}' on branch '{branch_name}' with commit '{commit_sha}'.")
    
    client = cloudbuild_v1.CloudBuildClient()
    
    # Configure the build request
    repo_source = cloudbuild_v1.RepoSource()
    repo_source.project_id = project_id
    repo_source.repo_name = repo_name
    repo_source.branch_name = branch_name
    repo_source.commit_sha = commit_sha
    
    try:
        # Trigger the build
        print("⚙️ Starting Cloud Build...")
        operation = client.run_build_trigger(
            project_id=project_id,
            trigger_id=trigger_id,
            source=repo_source
        )
        
        build_id = operation.metadata.build.id
        print(f"📋 Build started with ID: {build_id}")
        
        # Monitor the build
        print("⏳ Monitoring build progress...")
        build = client.get_build(project_id=project_id, id=build_id)
        
        while build.status in [cloudbuild_v1.Build.Status.QUEUED, cloudbuild_v1.Build.Status.WORKING]:
            time.sleep(10)
            build = client.get_build(project_id=project_id, id=build_id)
            print(f"🔄 Build status: {build.status.name}")
        
        # Build completed - capture detailed results
        final_status = build.status.name
        print(f"📊 Build completed with status: {final_status}")
        
        # Extract build logs if available
        build_logs = ""
        log_summary = ""
        if hasattr(build, 'log_url') and build.log_url:
            try:
                # Try to fetch and summarize logs
                build_logs = fetch_build_logs(build.log_url)
                if build_logs:
                    log_summary = summarize_build_logs_with_gemini(build_logs, final_status)
            except Exception as e:
                logging.warning(f"Could not fetch build logs: {e}")
                log_summary = f"Build logs available at: {build.log_url}"
        
        # Prepare response based on build status
        if build.status == cloudbuild_v1.Build.Status.SUCCESS:
            # Extract image information
            image_info = {}
            if build.results and build.results.images:
                first_image = build.results.images[0]
                image_info = {
                    "name": first_image.name,
                    "digest": first_image.digest
                }
            
            # Extract test results if available
            test_results = extract_test_results(build)
            
            success_message = f"Build completed successfully for {repo_name}:{branch_name}"
            if log_summary:
                success_message += f"\n\n📋 Build Summary:\n{log_summary}"
            
            return {
                "status": "SUCCESS",
                "message": success_message,
                "build_id": build_id,
                "image_uri_commit": f"{image_info.get('name', '')}",
                "details": {
                    "results": {
                        "images": [image_info] if image_info else []
                    }
                },
                "test_results": test_results,
                "build_logs": build_logs[:1000] if build_logs else "",  # First 1000 chars
                "log_summary": log_summary
            }
        else:
            # Build failed
            failure_message = f"Build failed with status: {final_status}"
            if log_summary:
                failure_message += f"\n\n🔍 Failure Analysis:\n{log_summary}"
            elif build.failure_info:
                failure_message += f"\nFailure details: {build.failure_info.detail}"
            
            return {
                "status": "FAILURE",
                "error_message": failure_message,
                "build_id": build_id,
                "build_logs": build_logs[:1000] if build_logs else "",
                "log_summary": log_summary
            }
            
    except Exception as e:
        error_msg = f"BTA Agent: Error during build trigger or monitoring: {e}"
        logging.exception(error_msg)
        return {"status": "ERROR", "error_message": error_msg}

def fetch_build_logs(log_url: str) -> str:
    """
    Fetch build logs from Cloud Storage URL.
    """
    try:
        # Extract bucket and object from log URL
        # Format: gs://bucket/path/to/log
        if not log_url.startswith('gs://'):
            return ""
        
        path_parts = log_url[5:].split('/', 1)  # Remove 'gs://' and split
        if len(path_parts) != 2:
            return ""
        
        bucket_name, object_name = path_parts
        
        # Download the log file
        storage_client = storage.Client()
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(object_name)
        
        # Download as text
        log_content = blob.download_as_text()
        return log_content
        
    except Exception as e:
        logging.warning(f"Could not fetch build logs from {log_url}: {e}")
        return ""

def summarize_build_logs_with_gemini(logs: str, build_status: str) -> str:
    """
    Use Gemini to summarize build logs and provide insights.
    """
    try:
        import google.generativeai as genai
        
        # Configure Gemini
        genai.configure(api_key=os.getenv('GEMINI_API_KEY'))
        model = genai.GenerativeModel('gemini-2.0-flash')
        
        prompt = f"""
        Analyze the following Cloud Build logs and provide a concise summary:
        
        Build Status: {build_status}
        
        Build Logs:
        {logs[:4000]}  # Limit to first 4000 characters
        
        Please provide:
        1. A brief summary of what the build did
        2. Key steps that were executed
        3. If the build failed, identify the specific error and suggest fixes
        4. If the build succeeded, highlight any important outputs or artifacts
        
        Keep the response concise and actionable.
        """
        
        response = model.generate_content(prompt)
        return response.text
        
    except Exception as e:
        logging.warning(f"Could not summarize logs with Gemini: {e}")
        return f"Build completed with status: {build_status}. Manual log review may be needed."

def extract_test_results(build) -> dict:
    """
    Extract test results from a completed build.
    
    This function checks if the build has associated test results in the 
    Google Cloud Storage bucket and parses them accordingly.
    """
    build_id = build.id
    logging.info(f"BTA: Extracting test results for build {build_id}")
    
    # Default response if no test results found
    default_result = {
        "test_status": "NO_TESTS",
        "message": "No test results found for this build."
    }
    
    try:
        commit_sha = None
        if hasattr(build, 'source') and hasattr(build.source, 'repo_source'):
            commit_sha = build.source.repo_source.commit_sha
        elif hasattr(build, 'substitutions') and build.substitutions:
            # Sometimes commit_sha is in substitutions
            commit_sha = build.substitutions.get('COMMIT_SHA') or build.substitutions.get('_COMMIT_SHA')
        
        if not commit_sha:
            logging.warning(f"BTA: Could not determine commit SHA for build {build_id}")
            return default_result
        
        test_results_path = f"test-results/{commit_sha}/test_results.json"
        
        # Try to download the test results from GCS
        test_json = _download_gcs_artifact(TEST_RESULTS_BUCKET_NAME, test_results_path)
        if not test_json:
            logging.info(f"BTA: No test results found at gs://{TEST_RESULTS_BUCKET_NAME}/{test_results_path}")
            # Try alternative path in case there's a variation
            alt_test_results_path = f"test-results/{commit_sha}/test_results.json"
            test_json = _download_gcs_artifact(TEST_RESULTS_BUCKET_NAME, alt_test_results_path)
            if not test_json:
                return default_result
        
        # Parse the test results
        results = _parse_go_test_json(test_json)
        
        # Get a summary of failures if there are any
        failure_summary = ""
        if results.get("failures", 0) > 0 and results.get("failure_details"):
            failure_summary = _summarize_test_failures_with_gemini(results["failure_details"])
        else:
            failure_summary = "All tests passed successfully."
        
        # Construct the result dictionary
        test_result = {
            "test_status": "PASSED" if results.get("failures", 0) == 0 else "FAILED",
            "tests_total": results.get("tests", 0),
            "tests_failed": results.get("failures", 0),
            "tests_skipped": results.get("skipped", 0),
            "failure_details": results.get("failure_details", []),
            "failure_summary": failure_summary
        }
        
        logging.info(f"BTA: Extracted test results: {test_result['tests_total']} tests, {test_result['tests_failed']} failures")
        return test_result
        
    except Exception as e:
        logging.error(f"BTA: Error extracting test results: {e}")
        return {
            "test_status": "ERROR",
            "message": f"Error extracting test results: {str(e)}"
        }

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

