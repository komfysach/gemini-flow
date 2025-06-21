# secops_agent.py
# Agent Development Kit (ADK) Security Agent for GeminiFlow

import os
import logging
import time # Imported for the retry sleep
from datetime import timedelta
from google.adk.agents import LlmAgent
from google.cloud.devtools import containeranalysis_v1

import google.generativeai as genai
from dotenv import load_dotenv
load_dotenv()

# Configure basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Security Agent Configuration ---
# For local testing, ensure GOOGLE_APPLICATION_CREDENTIALS is set to the path of
# the geminiflow-secops-sa@... service account key file.
# This SA needs "Artifact Analysis Reader" and "Vertex AI User" roles.
GCP_PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT")
# Vertex AI/Gemini configuration for summarization
GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL_NAME", "gemini-2.0-flash-latest")
VERTEX_AI_LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")

if GCP_PROJECT_ID and VERTEX_AI_LOCATION:
    try:
        genai.configure(
            api_key=os.getenv("GEMINI_API_KEY"), # Optional, will use ADC if not set
            client_options={"api_endpoint": f"{VERTEX_AI_LOCATION}-aiplatform.googleapis.com"}
        )
        logging.info(f"Security Agent: Gemini client configured for project {GCP_PROJECT_ID} and location {VERTEX_AI_LOCATION}")
    except Exception as e_genai:
        logging.warning(f"Security Agent: Could not configure Gemini client: {e_genai}. Summarization might fail.")
else:
    logging.warning("Security Agent: GCP_PROJECT_ID or VERTEX_AI_LOCATION not set. Gemini client for summarization not configured.")


# --- Security Agent Tools ---

def get_vulnerability_scan_results(image_uri_with_digest: str) -> dict:
    """
    Queries Google Cloud's Artifact Analysis API for vulnerability scan results for a specific container image digest.

    Args:
        image_uri_with_digest (str): The full URI of the Docker image including the sha256 digest.
                                     e.g., "us-central1-docker.pkg.dev/project/repo/image@sha256:..."

    Returns:
        dict: A dictionary containing the scan status and a list of found vulnerabilities.
    """
    if not GCP_PROJECT_ID:
        return {"status": "ERROR", "error_message": "GCP_PROJECT_ID environment variable not set."}
    if "@sha256:" not in image_uri_with_digest:
         return {"status": "ERROR", "error_message": f"Invalid image URI. Must include a sha256 digest. Got: {image_uri_with_digest}"}

    logging.info(f"Security Agent: Getting vulnerability scan results for {image_uri_with_digest}")
    
    try:
        client = containeranalysis_v1.ContainerAnalysisClient()
        resource_url = f"https://{image_uri_with_digest}"

        ga_client = client.get_grafeas_client()
        
        filter_str = f'kind="VULNERABILITY" AND resource_url="{resource_url}"'

        vulnerabilities = []
        max_retries = 3
        wait_seconds = 10
        for i in range(max_retries):
            page_result = ga_client.list_occurrences(
                parent=f"projects/{GCP_PROJECT_ID}",
                filter=filter_str
            )
            for occurrence in page_result:
                vulnerability = occurrence.vulnerability
                vuln_details = {
                    "severity": vulnerability.severity,
                    "cvss_score": vulnerability.cvss_score,
                    "package": vulnerability.package_issue[0].affected_package if vulnerability.package_issue else "N/A",
                    "version": vulnerability.package_issue[0].affected_version.full_name if vulnerability.package_issue else "N/A",
                    "description": vulnerability.short_description,
                    "cve": vulnerability.short_description.split(' ')[0]
                }
                vulnerabilities.append(vuln_details)
            
            if vulnerabilities:
                logging.info(f"Security Agent: Found {len(vulnerabilities)} vulnerabilities.")
                break
            
            if i < max_retries - 1:
                logging.info(f"Security Agent: No vulnerabilities found yet for {image_uri_with_digest}. Retrying in {wait_seconds} seconds... ({i+1}/{max_retries})")
                time.sleep(wait_seconds)
            else:
                logging.info(f"Security Agent: No vulnerabilities found for {image_uri_with_digest} after all retries.")

        return {
            "status": "SUCCESS",
            "vulnerability_count": len(vulnerabilities),
            "vulnerabilities": vulnerabilities,
            "message": f"Scan results retrieved. Found {len(vulnerabilities)} vulnerabilities."
        }

    except Exception as e:
        error_msg = f"Security Agent: Error querying Artifact Analysis API: {e}"
        logging.exception(error_msg)
        return {"status": "ERROR", "error_message": error_msg}


def summarize_vulnerabilities_with_gemini(scan_results: dict) -> str:
    """
    Uses Gemini to create a human-readable summary of vulnerability scan results.
    """
    if not scan_results or scan_results.get("status") != "SUCCESS":
        return "Could not generate summary because the vulnerability scan did not complete successfully."

    vulnerabilities = scan_results.get("vulnerabilities", [])
    if not vulnerabilities:
        return "Security Scan Summary: No vulnerabilities were found. The image is considered clean."

    prompt = "You are a DevSecOps analyst. Summarize the following container vulnerability scan results for a deployment decision. Be concise. List the number of vulnerabilities by severity (CRITICAL, HIGH, MEDIUM, LOW), and list details for any CRITICAL or HIGH severity issues. End with a brief recommendation.\n\n"
    prompt += "Vulnerability Data:\n"
    for vuln in vulnerabilities:
        prompt += f"- Severity: {vuln['severity']}, CVSS: {vuln['cvss_score']}, Package: {vuln['package']}@{vuln['version']}, CVE: {vuln['cve']}\n"
    
    try:
        logging.info("Security Agent: Sending vulnerability data to Gemini for summarization...")
        model = genai.GenerativeModel(GEMINI_MODEL_NAME)
        response = model.generate_content(prompt)
        summary = response.text.strip()
        logging.info("Security Agent: Gemini summarization successful.")
        return f"Security Scan Summary:\n{summary}"

    except Exception as e:
        logging.error(f"Security Agent: Error during Gemini summarization: {e}")
        return f"Could not summarize vulnerabilities due to an error. Found {len(vulnerabilities)} vulnerabilities."


# --- ADK Agent Definition ---
secops_agent = LlmAgent(
    name="geminiflow_secops_agent",
    model=GEMINI_MODEL_NAME, 
    description="An agent that analyzes container images for security vulnerabilities using Artifact Analysis and summarizes the findings.",
    instruction="You are a Security Agent. Your job is to get vulnerability scan results for a container image and summarize them.",
    tools=[
        get_vulnerability_scan_results,
        summarize_vulnerabilities_with_gemini,
    ],
)

# --- Local Testing Example ---
if __name__ == "__main__":
    if not GCP_PROJECT_ID or not VERTEX_AI_LOCATION:
         print("Error: Please set GOOGLE_CLOUD_PROJECT and GOOGLE_CLOUD_LOCATION environment variables.")
    else:
        test_image_uri_with_digest = "REPLACE_WITH_YOUR_REAL_IMAGE_URI_WITH_DIGEST"

        if test_image_uri_with_digest == "REPLACE_WITH_YOUR_REAL_IMAGE_URI_WITH_DIGEST":
            print("Error: Please update 'test_image_uri_with_digest' in the script with a valid image URI from Artifact Registry, including its sha256 digest.")
        else:
            print(f"--- Testing Security Agent Tools for image: {test_image_uri_with_digest} ---")
            scan_results = get_vulnerability_scan_results(image_uri_with_digest=test_image_uri_with_digest)
            
            print("\n--- Raw Scan Results ---")
            import json
            print(json.dumps(scan_results, indent=2))

            if scan_results.get("status") == "SUCCESS":
                print("\n--- Gemini Summary ---")
                summary = summarize_vulnerabilities_with_gemini(scan_results=scan_results)
                print(summary)
            else:
                print("\nCould not generate summary due to scan error.")
