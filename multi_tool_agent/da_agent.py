# da_agent.py
# Agent Development Kit (ADK) Deployment Agent (DA) for GeminiFlow
# Compatible with google-cloud-run v0.10.x for IAM calls

import os
import logging
import time
from google.adk.agents import Agent
from google.cloud import run_v2 
from google.api_core import exceptions as api_exceptions 
from google.iam.v1 import iam_policy_pb2
from google.iam.v1 import policy_pb2
from dotenv import load_dotenv 
load_dotenv() 

# Configure basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Configuration ---
GCP_PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT")
DEFAULT_CLOUD_RUN_REGION = os.getenv("CLOUD_RUN_REGION", "us-central1")
DEFAULT_SERVICE_NAME = "geminiflow-hello-world-svc"


# --- DA Tools ---

def deploy_to_cloud_run(
    project_id: str,
    region: str,
    service_name: str, 
    image_uri: str
) -> dict:
    """
    Deploys a container image to Google Cloud Run using Admin API v2.
    It will create the service if it doesn't exist, or update it if it does.
    Compatible with older google-cloud-run client library versions for IAM calls.
    """
    if not all([project_id, region, service_name, image_uri]):
        missing_params = [
            p for p, v in locals().items()
            if p in ["project_id", "region", "service_name", "image_uri"] and not v
        ]
        return {"status": "ERROR", "error_message": f"Missing required parameters: {', '.join(missing_params)}"}

    logging.info(f"Attempting to deploy to Cloud Run: project='{project_id}', region='{region}', service='{service_name}', image='{image_uri}'")

    try:
        client = run_v2.ServicesClient()
        parent = f"projects/{project_id}/locations/{region}"
        service_full_path = f"{parent}/services/{service_name}"

        service_template_config = run_v2.types.RevisionTemplate(
            containers=[
                run_v2.types.Container(
                    image=image_uri,
                    ports=[run_v2.types.ContainerPort(container_port=8080)],
                )
            ],
        )
        service_ingress_config = run_v2.types.IngressTraffic.INGRESS_TRAFFIC_ALL

        try:
            logging.info(f"Checking if service '{service_name}' already exists at '{service_full_path}'...")
            client.get_service(name=service_full_path)
            
            logging.info(f"Service '{service_name}' exists. Updating service...")
            service_config_for_update = run_v2.types.Service(
                name=service_full_path,
                template=service_template_config,
                ingress=service_ingress_config
            )
            operation = client.update_service(service=service_config_for_update)
            action_taken = "updated"

        except api_exceptions.NotFound:
            logging.info(f"Service '{service_name}' does not exist. Creating service...")
            service_config_for_create = run_v2.types.Service(
                template=service_template_config,
                ingress=service_ingress_config
            )
            operation = client.create_service(
                parent=parent,
                service=service_config_for_create,
                service_id=service_name
            )
            action_taken = "created"
        
        except Exception as e_check:
            error_msg = f"Error during service existence check or initial operation for '{service_name}': {str(e_check)}"
            logging.exception(error_msg)
            return { "status": "FAILURE", "service_name": service_name, "error_message": error_msg }

        logging.info(f"Deployment operation '{action_taken}' initiated for service '{service_name}'. Waiting for completion...")
        deployed_service = operation.result(timeout=600)

        service_url = deployed_service.uri
        logging.info(f"Service '{service_name}' {action_taken} successfully. URL: {service_url}")

        if deployed_service.ingress == run_v2.types.IngressTraffic.INGRESS_TRAFFIC_ALL:
            iam_policy_client = client 

            get_iam_request = iam_policy_pb2.GetIamPolicyRequest(resource=deployed_service.name)
            current_policy = iam_policy_client.get_iam_policy(request=get_iam_request)
            
            has_public_binding = any(
                binding.role == "roles/run.invoker" and "allUsers" in binding.members
                for binding in current_policy.bindings
            )

            if not has_public_binding:
                logging.info(f"Service '{service_name}' ingress is ALL but not yet publicly invokable. Setting IAM policy...")
                
                # Create a mutable copy of the policy to modify bindings
                # The Policy object from google.iam.v1.policy_pb2 is suitable.
                policy_to_set = policy_pb2.Policy()
                policy_to_set.CopyFrom(current_policy) # Start with the current policy
                
                new_binding = policy_pb2.Binding(role="roles/run.invoker", members=["allUsers"])
                policy_to_set.bindings.append(new_binding)
                # IMPORTANT: Set the etag from the fetched policy for optimistic concurrency control
                policy_to_set.etag = current_policy.etag
                
                # Use explicit request object for set_iam_policy
                set_iam_request = iam_policy_pb2.SetIamPolicyRequest(
                    resource=deployed_service.name,
                    policy=policy_to_set
                )
                iam_policy_client.set_iam_policy(request=set_iam_request)
                logging.info(f"IAM policy updated for public access to '{service_name}'.")
            else:
                logging.info(f"Service '{service_name}' is already publicly invokable.")

        return {
            "status": "SUCCESS",
            "service_name": service_name,
            "service_url": service_url,
            "message": f"Service '{service_name}' {action_taken} successfully."
        }

    except api_exceptions.PermissionDenied as e:
        error_msg = f"Permission denied during Cloud Run deployment for '{service_name}': {e}. Check DA SA permissions (Cloud Run Admin, Service Account User, roles/iam.serviceAccounts.setIamPolicy on the Run service if applicable)."
        logging.exception(error_msg)
        return {"status": "FAILURE", "service_name": service_name, "error_message": error_msg}
    except Exception as e:
        error_msg = f"An unexpected error occurred during Cloud Run deployment for service '{service_name}': {str(e)}"
        logging.exception(error_msg)
        return { "status": "FAILURE", "service_name": service_name, "error_message": error_msg }


def get_latest_deployed_image(
    project_id: str,
    region: str,
    service_name: str
) -> dict:
    """
    Retrieves the full image URI (with digest) of the latest revision serving traffic for a Cloud Run service.
    """
    logging.info(f"DA Agent: Getting latest deployed image for service '{service_name}' in '{region}'.")
    try:
        client = run_v2.ServicesClient()
        service_full_path = f"projects/{project_id}/locations/{region}/services/{service_name}"
        
        service = client.get_service(name=service_full_path)
        
        # The image URI with digest is in the service's template
        if service.template and service.template.containers:
            image_uri = service.template.containers[0].image
            if "@sha256:" in image_uri:
                logging.info(f"DA Agent: Found latest deployed image: {image_uri}")
                return {
                    "status": "SUCCESS",
                    "image_uri_with_digest": image_uri,
                    "message": f"Found latest deployed image for '{service_name}'."
                }
        
        return {"status": "FAILURE", "error_message": f"Could not find a container image URI for service '{service_name}'."}

    except api_exceptions.NotFound:
        error_msg = f"Service '{service_name}' not found in project '{project_id}' and location '{region}'."
        logging.error(f"DA Agent: {error_msg}")
        return {"status": "ERROR", "error_message": error_msg}
    except Exception as e:
        error_msg = f"An unexpected error occurred while getting the latest image for '{service_name}': {str(e)}"
        logging.exception(error_msg)
        return {"status": "FAILURE", "error_message": error_msg}
    
# --- ADK Agent Definition ---
da_agent = Agent(
    name="geminiflow_deployment_agent",
    description="An agent responsible for deploying containerized applications to runtime environments like Cloud Run.",
    instruction=(
        "You are a Deployment Agent. You receive requests to deploy specified container images "
        "to target environments (like Cloud Run) and report back the deployment status and service URL."
    ),
    tools=[deploy_to_cloud_run, get_latest_deployed_image],
)

# --- Local Testing Example ---
if __name__ == "__main__":
    if not GCP_PROJECT_ID:
        print("Error: GOOGLE_CLOUD_PROJECT environment variable is not set.")
    else:
        print(f"--- Testing DA: Deploying an image to Cloud Run ---")
      
        test_image_uri = "us-central1-docker.pkg.dev/geminiflow-461207/gemini-flow-apps/gemini-flow-hello-world:e8ae56197bcf9d12cb5b376c6893408a1079ff7b" # YOUR ACTUAL IMAGE URI

        if test_image_uri == "REPLACE_WITH_YOUR_IMAGE_URI_FROM_ARTIFACT_REGISTRY": 
            print("Error: Please update 'test_image_uri' in the script with a valid image URI from Artifact Registry.")
        else:
            deployment_report = deploy_to_cloud_run(
                project_id=GCP_PROJECT_ID,
                region=DEFAULT_CLOUD_RUN_REGION,
                service_name=DEFAULT_SERVICE_NAME,
                image_uri=test_image_uri
            )
            print("\n--- Deployment Report ---")
            if deployment_report:
                for key, value in deployment_report.items(): print(f"  {key}: {value}")
            else: print("  No report generated.")
            if deployment_report and deployment_report.get("status") == "SUCCESS":
                print(f"\nDA Test: SUCCESS - Service deployed. You can try accessing it at: {deployment_report.get('service_url')}")
            else: print("\nDA Test: FAILED or ERRORED - Check messages above.")