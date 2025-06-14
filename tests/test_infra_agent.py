# tests/test_infra_agent.py

import pytest
from unittest.mock import MagicMock, patch

# Adjust the path to find your agent files
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'multi_tool_agent')))

from infra_agent import run_terraform_plan, run_terraform_apply
from infra_agent import cloudbuild_v1

@pytest.fixture
def mock_cloud_build_client(mocker):
    """Mocks the google.cloud.devtools.cloudbuild_v1.CloudBuildClient."""
    mock_client_class = mocker.patch('infra_agent.cloudbuild_v1.CloudBuildClient')
    mock_client_instance = MagicMock()
    mock_client_class.return_value = mock_client_instance
    return mock_client_instance

def test_run_terraform_plan_success(mocker, mock_cloud_build_client):
    """Tests that 'terraform plan' is called correctly via the trigger."""
    # --- Mock Setup ---
    # MODIFIED: Patch the module-level variables directly
    mocker.patch('infra_agent.GCP_PROJECT_ID', 'test-project')
    mocker.patch('infra_agent.TERRAFORM_TRIGGER_ID', 'tf-trigger-123')
    mocker.patch('infra_agent.TERRAFORM_SOURCE_REPO_NAME', 'gemini-flow')
    
    # Mock the Cloud Build operation result
    mock_build_result = MagicMock()
    mock_build_result.status = cloudbuild_v1.Build.Status.SUCCESS
    mock_build_result.log_url = "[http://logs.example.com/plan](http://logs.example.com/plan)"
    mock_operation = MagicMock()
    mock_operation.result.return_value = mock_build_result
    mock_cloud_build_client.run_build_trigger.return_value = mock_operation

    # --- Function Call ---
    result = run_terraform_plan(
        new_service_name="staging-test",
        deployment_image_uri="gcr.io/test/image:latest",
        region="us-east1"
    )

    # --- Assertions ---
    assert result["status"] == "SUCCESS"
    assert "Terraform plan completed successfully" in result["message"]
    mock_cloud_build_client.run_build_trigger.assert_called_once()
    
    # Verify the arguments passed to the trigger run
    # The first argument is 'request', which isn't a keyword arg in some versions.
    # We can access it via call_args.kwargs if it's passed as a keyword, or call_args[0] if positional.
    # A safer way is to inspect the 'request' object itself.
    call_kwargs = mock_cloud_build_client.run_build_trigger.call_args.kwargs
    assert call_kwargs['project_id'] == "test-project"
    assert call_kwargs['trigger_id'] == "tf-trigger-123"
    
    # Verify the substitution variables
    substitutions = call_kwargs['source'].substitutions
    assert substitutions['_COMMAND'] == "plan"
    assert substitutions['_SERVICE_NAME'] == "staging-test"
    assert substitutions['_REGION'] == "us-east1"
    assert substitutions['_IMAGE_URI'] == "gcr.io/test/image:latest"

def test_run_terraform_apply_success(mocker, mock_cloud_build_client):
    """Tests that 'terraform apply' is called correctly via the trigger."""
    # --- Mock Setup ---
    mocker.patch('infra_agent.GCP_PROJECT_ID', 'test-project')
    mocker.patch('infra_agent.TERRAFORM_TRIGGER_ID', 'tf-trigger-123')
    mocker.patch('infra_agent.TERRAFORM_SOURCE_REPO_NAME', 'gemini-flow')
    
    mock_build_result = MagicMock()
    mock_build_result.status = cloudbuild_v1.Build.Status.SUCCESS
    mock_build_result.log_url = "[http://logs.example.com/apply](http://logs.example.com/apply)"
    mock_operation = MagicMock()
    mock_operation.result.return_value = mock_build_result
    mock_cloud_build_client.run_build_trigger.return_value = mock_operation

    # --- Function Call ---
    result = run_terraform_apply(
        new_service_name="prod-test",
        deployment_image_uri="gcr.io/test/image:prod",
        region="us-west1"
    )

    # --- Assertions ---
    assert result["status"] == "SUCCESS"
    assert "Terraform apply -auto-approve completed successfully" in result["message"]
    
    # Verify the substitution variables
    substitutions = mock_cloud_build_client.run_build_trigger.call_args.kwargs['source'].substitutions
    assert substitutions['_COMMAND'] == "apply -auto-approve"
    assert substitutions['_SERVICE_NAME'] == "prod-test"
    assert substitutions['_REGION'] == "us-west1"

def test_run_terraform_build_fails(mocker, mock_cloud_build_client):
    """Tests the failure path when the Cloud Build job for Terraform fails."""
    # --- Mock Setup ---
    mocker.patch('infra_agent.GCP_PROJECT_ID', 'test-project')
    mocker.patch('infra_agent.TERRAFORM_TRIGGER_ID', 'tf-trigger-123')
    mocker.patch('infra_agent.TERRAFORM_SOURCE_REPO_NAME', 'gemini-flow')
    
    mock_build_result = MagicMock()
    mock_build_result.status = cloudbuild_v1.Build.Status.FAILURE
    mock_build_result.log_url = "[http://logs.example.com/tf-fail](http://logs.example.com/tf-fail)"
    mock_operation = MagicMock()
    mock_operation.result.return_value = mock_build_result
    mock_cloud_build_client.run_build_trigger.return_value = mock_operation

    # --- Function Call ---
    result = run_terraform_plan("service", "image")

    # --- Assertions ---
    assert result["status"] == "FAILURE"
    assert "Terraform plan build failed" in result["error_message"]
    assert "[http://logs.example.com/tf-fail](http://logs.example.com/tf-fail)" in result["error_message"]
