# tests/test_infra_agent.py

import pytest
from unittest.mock import MagicMock, patch

# Adjust the path to find your agent files
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'multi_tool_agent')))

from infra_agent import (
    run_terraform_plan, 
    run_terraform_apply, 
    _parse_terraform_log,
    _get_build_logs_from_api,
    _extract_logs_from_build_object,
    _get_logs_from_cloud_logging,
    _save_log_to_terraform_bucket,
    _get_logs_from_terraform_bucket
)
from google.cloud.devtools import cloudbuild_v1

@pytest.fixture
def mock_cloud_build_client(mocker):
    """Mocks the google.cloud.devtools.cloudbuild_v1.CloudBuildClient."""
    mock_client_class = mocker.patch('infra_agent.cloudbuild_v1.CloudBuildClient')
    mock_client_instance = MagicMock()
    mock_client_class.return_value = mock_client_instance
    return mock_client_instance

@pytest.fixture
def mock_storage_client(mocker):
    """Mocks the google.cloud.storage.Client."""
    mock_storage_client_class = mocker.patch('infra_agent.storage.Client')
    mock_storage_client_instance = MagicMock()
    mock_storage_client_class.return_value = mock_storage_client_instance
    return mock_storage_client_instance

def test_run_terraform_plan_success(mocker, mock_cloud_build_client):
    """Tests that 'terraform plan' is called correctly via the trigger."""
    # --- Mock Setup ---
    mocker.patch('infra_agent.GCP_PROJECT_ID', 'test-project')
    mocker.patch('infra_agent.TERRAFORM_TRIGGER_ID', 'tf-trigger-123')
    mocker.patch('infra_agent.TERRAFORM_SOURCE_REPO', 'gemini-flow')
    mocker.patch('infra_agent.TERRAFORM_LOGS_BUCKET', 'test-logs-bucket')
    
    # Mock the Cloud Build operation result
    mock_build_result = MagicMock()
    mock_build_result.status = cloudbuild_v1.Build.Status.SUCCESS
    mock_build_result.log_url = "https://console.cloud.google.com/cloud-build/builds/build-12345?project=test-project"
    mock_build_result.logs_bucket = "test-logs-bucket"
    mock_build_result.id = "build-12345"
    
    mock_operation = MagicMock()
    mock_operation.result.return_value = mock_build_result
    mock_cloud_build_client.run_build_trigger.return_value = mock_operation
    
    # Mock the log retrieval functions
    mock_log_content = "Plan: 2 to add, 1 to change, 0 to destroy."
    mocker.patch('infra_agent._get_build_logs_from_api', return_value=mock_log_content)
    mocker.patch('infra_agent._save_log_to_terraform_bucket', return_value=True)
    mocker.patch('infra_agent._summarize_terraform_output_with_gemini', return_value="AI summary of terraform plan")

    # --- Function Call ---
    result = run_terraform_plan(
        new_service_name="staging-test",
        deployment_image_uri="gcr.io/test/image:latest",
        region="us-east1"
    )

    # --- Assertions ---
    assert result["status"] == "SUCCESS"
    assert "Terraform Plan Summary: 2 to add, 1 to change, 0 to destroy." in result["message"]
    assert result["log_url"] == "https://console.cloud.google.com/cloud-build/builds/build-12345?project=test-project"
    assert result["build_id"] == "build-12345"
    assert result["log_retrieved"] == True
    assert result["logs_bucket"] == "test-logs-bucket"
    assert result["log_path"] == "terraform-logs/plan/build-12345/terraform_log.txt"
    
    mock_cloud_build_client.run_build_trigger.assert_called_once()
    
    # Verify the arguments passed to the trigger run
    call_kwargs = mock_cloud_build_client.run_build_trigger.call_args.kwargs
    assert call_kwargs['project_id'] == "test-project"
    assert call_kwargs['trigger_id'] == "tf-trigger-123"
    
    # Verify the source configuration
    source = call_kwargs['source']
    assert source.repo_name == "gemini-flow"
    assert source.branch_name == "main"
    
    # Verify the substitution variables
    substitutions = source.substitutions
    assert substitutions['_COMMAND'] == "plan"
    assert substitutions['_SERVICE_NAME'] == "staging-test"
    assert substitutions['_REGION'] == "us-east1"
    assert substitutions['_IMAGE_URI'] == "gcr.io/test/image:latest"

def test_run_terraform_apply_success(mocker, mock_cloud_build_client):
    """Tests that 'terraform apply' is called correctly via the trigger."""
    # --- Mock Setup ---
    mocker.patch('infra_agent.GCP_PROJECT_ID', 'test-project')
    mocker.patch('infra_agent.TERRAFORM_TRIGGER_ID', 'tf-trigger-123')
    mocker.patch('infra_agent.TERRAFORM_SOURCE_REPO', 'gemini-flow')
    mocker.patch('infra_agent.TERRAFORM_LOGS_BUCKET', 'test-logs-bucket')
    
    mock_build_result = MagicMock()
    mock_build_result.status = cloudbuild_v1.Build.Status.SUCCESS
    mock_build_result.log_url = "https://console.cloud.google.com/cloud-build/builds/build-67890?project=test-project"
    mock_build_result.logs_bucket = "test-logs-bucket"
    mock_build_result.id = "build-67890"
    
    mock_operation = MagicMock()
    mock_operation.result.return_value = mock_build_result
    mock_cloud_build_client.run_build_trigger.return_value = mock_operation
    
    # Mock the log retrieval with service URL
    mock_log_content = '''Apply complete! Resources: 2 added, 0 changed, 0 destroyed.
    
    Outputs:
    
    service_url = "https://prod-test-123-uc.a.run.app"'''
    mocker.patch('infra_agent._get_build_logs_from_api', return_value=mock_log_content)
    mocker.patch('infra_agent._save_log_to_terraform_bucket', return_value=True)
    mocker.patch('infra_agent._summarize_terraform_output_with_gemini', return_value="AI summary of terraform apply")

    # --- Function Call ---
    result = run_terraform_apply(
        new_service_name="prod-test",
        deployment_image_uri="gcr.io/test/image:prod",
        region="us-west1"
    )

    # --- Assertions ---
    assert result["status"] == "SUCCESS"
    assert "Terraform apply complete. New service URL: https://prod-test-123-uc.a.run.app" in result["message"]
    assert result["ai_summary"] == "AI summary of terraform apply"
    
    # Verify the substitution variables
    source = mock_cloud_build_client.run_build_trigger.call_args.kwargs['source']
    substitutions = source.substitutions
    assert substitutions['_COMMAND'] == "apply -auto-approve"
    assert substitutions['_SERVICE_NAME'] == "prod-test"
    assert substitutions['_REGION'] == "us-west1"

def test_run_terraform_build_fails(mocker, mock_cloud_build_client):
    """Tests the failure path when the Cloud Build job for Terraform fails."""
    # --- Mock Setup ---
    mocker.patch('infra_agent.GCP_PROJECT_ID', 'test-project')
    mocker.patch('infra_agent.TERRAFORM_TRIGGER_ID', 'tf-trigger-123')
    mocker.patch('infra_agent.TERRAFORM_SOURCE_REPO', 'gemini-flow')
    mocker.patch('infra_agent.TERRAFORM_LOGS_BUCKET', 'test-logs-bucket')
    
    mock_build_result = MagicMock()
    mock_build_result.status = cloudbuild_v1.Build.Status.FAILURE
    mock_build_result.log_url = "https://console.cloud.google.com/cloud-build/builds/build-fail?project=test-project"
    mock_build_result.id = "build-fail"
    
    mock_operation = MagicMock()
    mock_operation.result.return_value = mock_build_result
    mock_cloud_build_client.run_build_trigger.return_value = mock_operation
    
    # Mock log retrieval even for failures
    mocker.patch('infra_agent._get_build_logs_from_api', return_value="Terraform failed with errors")
    mocker.patch('infra_agent._save_log_to_terraform_bucket', return_value=True)

    # --- Function Call ---
    result = run_terraform_plan("service", "image")

    # --- Assertions ---
    assert result["status"] == "FAILURE"
    assert "Terraform plan build failed" in result["error_message"]
    assert result["log_retrieved"] == True
    assert result["logs_bucket"] == "test-logs-bucket"

def test_run_terraform_exception_handling(mocker, mock_cloud_build_client):
    """Tests exception handling when Cloud Build trigger fails."""
    # --- Mock Setup ---
    mocker.patch('infra_agent.GCP_PROJECT_ID', 'test-project')
    mocker.patch('infra_agent.TERRAFORM_TRIGGER_ID', 'tf-trigger-123')
    
    # Mock an exception during trigger execution
    mock_cloud_build_client.run_build_trigger.side_effect = Exception("Trigger not found")

    # --- Function Call ---
    result = run_terraform_apply("test-service", "gcr.io/test/image:latest")

    # --- Assertions ---
    assert result["status"] == "ERROR"
    assert "Failed to run Terraform trigger" in result["error_message"]
    assert "Trigger not found" in result["error_message"]

def test_get_build_logs_from_api_success(mocker, mock_cloud_build_client):
    """Tests successful log retrieval from Cloud Build API."""
    # --- Mock Setup ---
    mocker.patch('infra_agent.GCP_PROJECT_ID', 'test-project')
    
    mock_build = MagicMock()
    mock_build.status = cloudbuild_v1.Build.Status.SUCCESS
    mock_build.id = "build-12345"
    mock_build.logs_bucket = "test-logs-bucket"
    mock_cloud_build_client.get_build.return_value = mock_build
    
    # Mock log extraction
    mock_log_content = "Terraform execution logs"
    mocker.patch('infra_agent._extract_logs_from_build_object', return_value=mock_log_content)

    # --- Function Call ---
    log_content = _get_build_logs_from_api("build-12345")

    # --- Assertions ---
    assert log_content == "Terraform execution logs"
    mock_cloud_build_client.get_build.assert_called_with(project_id="test-project", id="build-12345")

def test_get_build_logs_from_api_build_running(mocker, mock_cloud_build_client):
    """Tests log retrieval when build is still running."""
    # --- Mock Setup ---
    mocker.patch('infra_agent.GCP_PROJECT_ID', 'test-project')
    
    # First call: build is working
    mock_build_working = MagicMock()
    mock_build_working.status = cloudbuild_v1.Build.Status.WORKING
    mock_build_working.id = "build-12345"
    
    # Second call: build is complete
    mock_build_complete = MagicMock()
    mock_build_complete.status = cloudbuild_v1.Build.Status.SUCCESS
    mock_build_complete.id = "build-12345"
    mock_build_complete.logs_bucket = "test-logs-bucket"
    
    mock_cloud_build_client.get_build.side_effect = [mock_build_working, mock_build_complete]
    
    # Mock log extraction
    mocker.patch('infra_agent._extract_logs_from_build_object', return_value="Final logs")
    
    # Mock time.sleep to speed up test
    mocker.patch('infra_agent.time.sleep')

    # --- Function Call ---
    log_content = _get_build_logs_from_api("build-12345")

    # --- Assertions ---
    assert log_content == "Final logs"
    assert mock_cloud_build_client.get_build.call_count == 2

def test_extract_logs_from_build_object_gcs_success(mocker, mock_storage_client):
    """Tests extracting logs from GCS bucket in build object."""
    # --- Mock Setup ---
    mocker.patch('infra_agent.GCP_PROJECT_ID', 'test-project')
    
    mock_build = MagicMock()
    mock_build.logs_bucket = "test-logs-bucket"
    mock_build.id = "build-12345"
    
    mock_bucket = MagicMock()
    mock_blob = MagicMock()
    mock_blob.exists.return_value = True
    mock_blob.download_as_text.return_value = "GCS log content"
    mock_bucket.blob.return_value = mock_blob
    mock_storage_client.bucket.return_value = mock_bucket

    # --- Function Call ---
    log_content = _extract_logs_from_build_object(mock_build)

    # --- Assertions ---
    assert log_content == "GCS log content"
    mock_storage_client.bucket.assert_called_with("test-logs-bucket")

@patch('google.cloud.logging.Client')
def test_get_logs_from_cloud_logging_success(mock_logging_client_class, mocker):
    """Tests successful log retrieval from Cloud Logging."""
    # --- Mock Setup ---
    mocker.patch('infra_agent.GCP_PROJECT_ID', 'test-project')
    
    mock_logging_client = MagicMock()
    mock_logging_client_class.return_value = mock_logging_client
    
    # Create proper mock entries with actual string values
    mock_entry1 = MagicMock()
    mock_entry1.text_payload = "Log line 1"
    mock_entry1.payload = None  # Make sure payload is None so text_payload is used
    
    mock_entry2 = MagicMock()
    mock_entry2.text_payload = "Log line 2"
    mock_entry2.payload = None  # Make sure payload is None so text_payload is used
    
    # Configure hasattr checks
    def mock_hasattr(obj, attr):
        if attr == 'payload' and obj in [mock_entry1, mock_entry2]:
            return True
        if attr == 'text_payload' and obj in [mock_entry1, mock_entry2]:
            return True
        return False
    
    mocker.patch('builtins.hasattr', side_effect=mock_hasattr)
    mock_logging_client.list_entries.return_value = [mock_entry1, mock_entry2]

    # --- Function Call ---
    log_content = _get_logs_from_cloud_logging("build-12345")

    # --- Assertions ---
    assert log_content == "Log line 1\nLog line 2"
    mock_logging_client.list_entries.assert_called_once()
    mock_logging_client_class.assert_called_with(project="test-project")

@patch('google.cloud.logging.Client')
def test_get_logs_from_cloud_logging_with_payload(mock_logging_client_class, mocker):
    """Tests Cloud Logging when entries have payload instead of text_payload."""
    # --- Mock Setup ---
    mocker.patch('infra_agent.GCP_PROJECT_ID', 'test-project')
    
    mock_logging_client = MagicMock()
    mock_logging_client_class.return_value = mock_logging_client
    
    # Create mock entries with payload instead of text_payload
    mock_entry1 = MagicMock()
    mock_entry1.payload = "Payload line 1"
    mock_entry1.text_payload = None
    
    mock_entry2 = MagicMock()
    mock_entry2.payload = "Payload line 2"
    mock_entry2.text_payload = None
    
    # Configure hasattr checks properly
    def mock_hasattr(obj, attr):
        if obj == mock_entry1:
            if attr == 'payload':
                return mock_entry1.payload is not None
            if attr == 'text_payload':
                return mock_entry1.text_payload is not None
        if obj == mock_entry2:
            if attr == 'payload':
                return mock_entry2.payload is not None
            if attr == 'text_payload':
                return mock_entry2.text_payload is not None
        return False
    
    mocker.patch('builtins.hasattr', side_effect=mock_hasattr)
    mock_logging_client.list_entries.return_value = [mock_entry1, mock_entry2]

    # --- Function Call ---
    log_content = _get_logs_from_cloud_logging("build-12345")

    # --- Assertions ---
    assert log_content == "Payload line 1\nPayload line 2"

@patch('google.cloud.logging.Client')
def test_get_logs_from_cloud_logging_no_entries(mock_logging_client_class, mocker):
    """Tests Cloud Logging when no entries are found."""
    # --- Mock Setup ---
    mocker.patch('infra_agent.GCP_PROJECT_ID', 'test-project')
    
    mock_logging_client = MagicMock()
    mock_logging_client_class.return_value = mock_logging_client
    mock_logging_client.list_entries.return_value = []

    # --- Function Call ---
    log_content = _get_logs_from_cloud_logging("build-12345")

    # --- Assertions ---
    assert log_content is None

def test_save_log_to_terraform_bucket_success(mocker, mock_storage_client):
    """Tests successful saving of logs to TERRAFORM_LOGS_BUCKET."""
    # --- Mock Setup ---
    mocker.patch('infra_agent.GCP_PROJECT_ID', 'test-project')
    mocker.patch('infra_agent.TERRAFORM_LOGS_BUCKET', 'test-terraform-logs')
    
    mock_bucket = MagicMock()
    mock_blob = MagicMock()
    mock_bucket.blob.return_value = mock_blob
    mock_storage_client.bucket.return_value = mock_bucket

    # --- Function Call ---
    result = _save_log_to_terraform_bucket("log content", "build-12345", "plan")

    # --- Assertions ---
    assert result == True
    mock_storage_client.bucket.assert_called_with("test-terraform-logs")
    mock_bucket.blob.assert_called_with("terraform-logs/plan/build-12345/terraform_log.txt")
    mock_blob.upload_from_string.assert_called_with("log content")

def test_save_log_to_terraform_bucket_failure(mocker, mock_storage_client):
    """Tests failure when saving logs to TERRAFORM_LOGS_BUCKET."""
    # --- Mock Setup ---
    mocker.patch('infra_agent.GCP_PROJECT_ID', 'test-project')
    mocker.patch('infra_agent.TERRAFORM_LOGS_BUCKET', 'test-terraform-logs')
    
    mock_storage_client.bucket.side_effect = Exception("Storage error")

    # --- Function Call ---
    result = _save_log_to_terraform_bucket("log content", "build-12345", "plan")

    # --- Assertions ---
    assert result == False

def test_get_logs_from_terraform_bucket_success(mocker, mock_storage_client):
    """Tests successful retrieval of logs from TERRAFORM_LOGS_BUCKET."""
    # --- Mock Setup ---
    mocker.patch('infra_agent.GCP_PROJECT_ID', 'test-project')
    mocker.patch('infra_agent.TERRAFORM_LOGS_BUCKET', 'test-terraform-logs')
    
    mock_bucket = MagicMock()
    mock_blob = MagicMock()
    mock_blob.exists.return_value = True
    mock_blob.download_as_text.return_value = "stored log content"
    mock_bucket.blob.return_value = mock_blob
    mock_storage_client.bucket.return_value = mock_bucket

    # --- Function Call ---
    log_content = _get_logs_from_terraform_bucket("build-12345", "apply -auto-approve")

    # --- Assertions ---
    assert log_content == "stored log content"
    mock_storage_client.bucket.assert_called_with("test-terraform-logs")
    mock_bucket.blob.assert_called_with("terraform-logs/apply -auto-approve/build-12345/terraform_log.txt")

def test_get_logs_from_terraform_bucket_not_found(mocker, mock_storage_client):
    """Tests retrieval when logs don't exist in TERRAFORM_LOGS_BUCKET."""
    # --- Mock Setup ---
    mocker.patch('infra_agent.GCP_PROJECT_ID', 'test-project')
    mocker.patch('infra_agent.TERRAFORM_LOGS_BUCKET', 'test-terraform-logs')
    
    mock_bucket = MagicMock()
    mock_blob = MagicMock()
    mock_blob.exists.return_value = False
    mock_bucket.blob.return_value = mock_blob
    mock_storage_client.bucket.return_value = mock_bucket

    # --- Function Call ---
    log_content = _get_logs_from_terraform_bucket("build-12345", "plan")

    # --- Assertions ---
    assert log_content is None

def test_parse_terraform_log_plan_success():
    """Tests parsing of terraform plan logs."""
    log_text = """
    Terraform will perform the following actions:
    
    Plan: 3 to add, 1 to change, 0 to destroy.
    
    Do you want to perform these actions?
    """
    
    result = _parse_terraform_log(log_text, "plan")
    assert result == "Terraform Plan Summary: 3 to add, 1 to change, 0 to destroy."

def test_parse_terraform_log_plan_no_summary():
    """Tests parsing when plan summary is not found."""
    log_text = "Some terraform output without plan summary"
    
    result = _parse_terraform_log(log_text, "plan")
    assert result == "Terraform plan ran, but summary line could not be found in logs."

def test_parse_terraform_log_apply_success():
    """Tests parsing of terraform apply logs."""
    log_text = """
    Apply complete! Resources: 2 added, 1 changed, 0 destroyed.
    
    Outputs:
    
    service_url = "https://my-service-123-uc.a.run.app"
    """
    
    result = _parse_terraform_log(log_text, "apply -auto-approve")
    assert result == "Terraform apply complete. New service URL: https://my-service-123-uc.a.run.app"

def test_parse_terraform_log_apply_successful_no_url():
    """Tests parsing when apply is successful but service URL not found."""
    log_text = "Apply complete! Resources: 1 added, 0 changed, 0 destroyed."
    
    result = _parse_terraform_log(log_text, "apply -auto-approve")
    assert result == "Terraform apply completed successfully, but service_url output could not be parsed from logs."

def test_parse_terraform_log_unknown_command():
    """Tests parsing with unknown command."""
    result = _parse_terraform_log("some log", "unknown")
    assert result == "Unknown command for log parsing."

def test_parse_terraform_log_empty():
    """Tests parsing with empty log text."""
    result = _parse_terraform_log("", "plan")
    assert result == "Could not retrieve logs to parse for Terraform plan result."

def test_run_terraform_plan_no_logs(mocker, mock_cloud_build_client):
    """Tests terraform plan when logs cannot be retrieved."""
    # --- Mock Setup ---
    mocker.patch('infra_agent.GCP_PROJECT_ID', 'test-project')
    mocker.patch('infra_agent.TERRAFORM_TRIGGER_ID', 'tf-trigger-123')
    mocker.patch('infra_agent.TERRAFORM_LOGS_BUCKET', 'test-logs-bucket')
    
    mock_build_result = MagicMock()
    mock_build_result.status = cloudbuild_v1.Build.Status.SUCCESS
    mock_build_result.log_url = "https://console.cloud.google.com/cloud-build/builds/build-12345?project=test-project"
    mock_build_result.logs_bucket = "test-logs-bucket"
    mock_build_result.id = "build-12345"
    
    mock_operation = MagicMock()
    mock_operation.result.return_value = mock_build_result
    mock_cloud_build_client.run_build_trigger.return_value = mock_operation
    
    # Mock no logs retrieved
    mocker.patch('infra_agent._get_build_logs_from_api', return_value=None)

    # --- Function Call ---
    result = run_terraform_plan("test-service", "gcr.io/test/image:latest")

    # --- Assertions ---
    assert result["status"] == "SUCCESS_NO_LOGS"
    assert f"Terraform plan completed successfully, but logs could not be copied to test-logs-bucket" in result["message"]
    assert result["log_retrieved"] == False

def test_run_terraform_success_with_logs_but_save_fails(mocker, mock_cloud_build_client):
    """Tests when logs are retrieved but saving to bucket fails."""
    # --- Mock Setup ---
    mocker.patch('infra_agent.GCP_PROJECT_ID', 'test-project')
    mocker.patch('infra_agent.TERRAFORM_TRIGGER_ID', 'tf-trigger-123')
    mocker.patch('infra_agent.TERRAFORM_LOGS_BUCKET', 'test-logs-bucket')
    
    mock_build_result = MagicMock()
    mock_build_result.status = cloudbuild_v1.Build.Status.SUCCESS
    mock_build_result.log_url = "https://console.cloud.google.com/cloud-build/builds/build-12345?project=test-project"
    mock_build_result.id = "build-12345"
    
    mock_operation = MagicMock()
    mock_operation.result.return_value = mock_build_result
    mock_cloud_build_client.run_build_trigger.return_value = mock_operation
    
    # Mock logs retrieved but save fails
    mock_log_content = "Plan: 1 to add, 0 to change, 0 to destroy."
    mocker.patch('infra_agent._get_build_logs_from_api', return_value=mock_log_content)
    mocker.patch('infra_agent._save_log_to_terraform_bucket', return_value=False)
    mocker.patch('infra_agent._summarize_terraform_output_with_gemini', return_value="AI summary")

    # --- Function Call ---
    result = run_terraform_plan("test-service", "gcr.io/test/image:latest")

    # --- Assertions ---
    assert result["status"] == "SUCCESS"
    assert "Terraform Plan Summary: 1 to add, 0 to change, 0 to destroy." in result["message"]
    assert result["log_retrieved"] == True  # Logs were retrieved, even if save failed