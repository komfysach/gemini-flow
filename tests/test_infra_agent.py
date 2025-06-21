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
    _get_build_logs,
    _save_log_archive
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
    """Tests that 'terraform plan' is called correctly and processes logs."""
    # --- Mock Setup ---
    mocker.patch('infra_agent.GCP_PROJECT_ID', 'test-project')
    mocker.patch('infra_agent.TERRAFORM_TRIGGER_ID', 'tf-trigger-123')
    mocker.patch('infra_agent.TERRAFORM_SOURCE_REPO', 'gemini-flow')
    mocker.patch('infra_agent.TERRAFORM_LOGS_BUCKET', 'test-logs-bucket')
    
    mock_build_result = MagicMock()
    mock_build_result.status = cloudbuild_v1.Build.Status.SUCCESS
    mock_build_result.log_url = "https://console.cloud.google.com/cloud-build/builds/build-12345"
    mock_build_result.id = "build-12345"
    
    mock_operation = MagicMock()
    mock_operation.result.return_value = mock_build_result
    mock_cloud_build_client.run_build_trigger.return_value = mock_operation
    
    # Mock the NEW log retrieval function
    mock_log_content = "Plan: 2 to add, 1 to change, 0 to destroy."
    mocker.patch('infra_agent._get_build_logs', return_value=mock_log_content)
    mocker.patch('infra_agent._save_log_archive')
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
    assert result["log_retrieved"] == True
    
    # Verify the trigger was called with the correct substitutions
    call_kwargs = mock_cloud_build_client.run_build_trigger.call_args.kwargs
    substitutions = call_kwargs['source'].substitutions
    assert substitutions['_COMMAND'] == "plan"
    assert substitutions['_SERVICE_NAME'] == "staging-test"

def test_run_terraform_apply_success(mocker, mock_cloud_build_client):
    """Tests that 'terraform apply' is called correctly and processes logs."""
    # --- Mock Setup ---
    mocker.patch('infra_agent.GCP_PROJECT_ID', 'test-project')
    mocker.patch('infra_agent.TERRAFORM_TRIGGER_ID', 'tf-trigger-123')
    
    mock_build_result = MagicMock()
    mock_build_result.status = cloudbuild_v1.Build.Status.SUCCESS
    mock_operation = MagicMock()
    mock_operation.result.return_value = mock_build_result
    mock_cloud_build_client.run_build_trigger.return_value = mock_operation
    
    mock_log_content = 'Outputs:\n\nservice_url = "https://prod-test-123-uc.a.run.app"'
    mocker.patch('infra_agent._get_build_logs', return_value=mock_log_content)
    mocker.patch('infra_agent._save_log_archive')
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
    
    # Verify the substitution variables
    source = mock_cloud_build_client.run_build_trigger.call_args.kwargs['source']
    assert source.substitutions['_COMMAND'] == "apply -auto-approve"

def test_run_terraform_build_fails(mocker, mock_cloud_build_client):
    """Tests the failure path when the Cloud Build job for Terraform fails."""
    # --- Mock Setup ---
    mock_build_result = MagicMock()
    mock_build_result.status = cloudbuild_v1.Build.Status.FAILURE
    mock_build_result.log_url = "https://log-url"
    mock_operation = MagicMock()
    mock_operation.result.return_value = mock_build_result
    mock_cloud_build_client.run_build_trigger.return_value = mock_operation
    
    mocker.patch('infra_agent._get_build_logs', return_value="Terraform failed with errors")
    mocker.patch('infra_agent._save_log_archive')
    mocker.patch('infra_agent._summarize_terraform_output_with_gemini', return_value="AI analysis of failure")

    # --- Function Call ---
    result = run_terraform_plan("service", "image")

    # --- Assertions ---
    assert result["status"] == "FAILURE"
    assert "Terraform plan build failed" in result["error_message"]
    assert "AI analysis of failure" in result["error_message"]
    assert result["log_retrieved"] == True

def test_run_terraform_success_no_logs(mocker, mock_cloud_build_client):
    """Tests the path where the build succeeds but log retrieval fails."""
    # --- Mock Setup ---
    mock_build_result = MagicMock()
    mock_build_result.status = cloudbuild_v1.Build.Status.SUCCESS
    mock_operation = MagicMock()
    mock_operation.result.return_value = mock_build_result
    mock_cloud_build_client.run_build_trigger.return_value = mock_operation
    
    # Mock log retrieval returning None
    mocker.patch('infra_agent._get_build_logs', return_value=None)

    # --- Function Call ---
    result = run_terraform_plan("test-service", "gcr.io/test/image:latest")

    # --- Assertions ---
    assert result["status"] == "SUCCESS_NO_LOGS"
    assert "logs could not be retrieved" in result["message"]
    assert result["log_retrieved"] == False

def test_get_build_logs_success_with_retry(mocker, mock_storage_client):
    """Tests that _get_build_logs retries and eventually succeeds."""
    # --- Mock Setup ---
    mock_sleep = mocker.patch('infra_agent.time.sleep') # Store the mock object
    
    mock_build_result = MagicMock()
    mock_build_result.logs_bucket = "gs://test-log-bucket"
    mock_build_result.id = "build-123"
    
    mock_bucket = MagicMock()
    mock_blob = MagicMock()
    # Fail the first two existence checks, then succeed
    mock_blob.exists.side_effect = [False, False, True]
    mock_blob.download_as_text.return_value = "Log content"
    mock_bucket.blob.return_value = mock_blob
    mock_storage_client.bucket.return_value = mock_bucket

    # --- Function Call ---
    log_content = _get_build_logs(mock_build_result)

    # --- Assertions ---
    assert log_content == "Log content"
    assert mock_blob.exists.call_count == 3
    # Verify sleep was called 2 times (for the first 2 failed attempts)
    assert mock_sleep.call_count == 2

def test_get_build_logs_fails_after_retries(mocker, mock_storage_client):
    """Tests that _get_build_logs returns None if the log never appears."""
    # --- Mock Setup ---
    mock_sleep = mocker.patch('infra_agent.time.sleep') # Store the mock object
    
    mock_build_result = MagicMock()
    mock_build_result.logs_bucket = "gs://test-log-bucket"
    mock_build_result.id = "build-123"
    
    mock_bucket = MagicMock()
    mock_blob = MagicMock()
    # Always fail the existence check
    mock_blob.exists.return_value = False
    mock_bucket.blob.return_value = mock_blob
    mock_storage_client.bucket.return_value = mock_bucket

    # --- Function Call ---
    log_content = _get_build_logs(mock_build_result)

    # --- Assertions ---
    assert log_content is None
    assert mock_blob.exists.call_count == 6 # It should try 6 times
    assert mock_sleep.call_count == 6 # Should sleep 6 times (after each failed attempt)

def test_get_build_logs_invalid_logs_bucket(mocker):
    """Tests _get_build_logs with invalid logs_bucket path."""
    mock_build_result = MagicMock()
    mock_build_result.logs_bucket = "invalid-path"
    mock_build_result.id = "build-123"

    # --- Function Call ---
    log_content = _get_build_logs(mock_build_result)

    # --- Assertions ---
    assert log_content is None

def test_save_log_archive_success(mocker, mock_storage_client):
    """Tests successful saving of logs to the archive bucket."""
    # --- Mock Setup ---
    mocker.patch('infra_agent.TERRAFORM_LOGS_BUCKET', 'test-archive-bucket')
    
    mock_bucket = MagicMock()
    mock_blob = MagicMock()
    mock_bucket.blob.return_value = mock_blob
    mock_storage_client.bucket.return_value = mock_bucket

    # --- Function Call ---
    _save_log_archive("log content", "build-123", "plan")

    # --- Assertions ---
    mock_storage_client.bucket.assert_called_with("test-archive-bucket")
    mock_bucket.blob.assert_called_with("terraform-logs/plan/build-123/terraform_log.txt")
    mock_blob.upload_from_string.assert_called_with("log content")

def test_save_log_archive_no_bucket_configured(mocker):
    """Tests _save_log_archive when TERRAFORM_LOGS_BUCKET is not set."""
    # --- Mock Setup ---
    mocker.patch('infra_agent.TERRAFORM_LOGS_BUCKET', None)

    # --- Function Call ---
    _save_log_archive("log content", "build-123", "plan")

    # --- Assertions ---
    # Should not raise an exception, just log a warning

def test_save_log_archive_failure(mocker, mock_storage_client):
    """Tests failure when saving logs to archive bucket."""
    # --- Mock Setup ---
    mocker.patch('infra_agent.TERRAFORM_LOGS_BUCKET', 'test-archive-bucket')
    
    mock_storage_client.bucket.side_effect = Exception("Storage error")

    # --- Function Call ---
    _save_log_archive("log content", "build-123", "plan")

    # --- Assertions ---
    # Should not raise an exception, just log the error

def test_parse_terraform_log_plan_success():
    """Tests parsing of terraform plan logs."""
    log_text = "Plan: 3 to add, 1 to change, 0 to destroy."
    result = _parse_terraform_log(log_text, "plan")
    assert result == "Terraform Plan Summary: 3 to add, 1 to change, 0 to destroy."

def test_parse_terraform_log_plan_no_summary():
    """Tests parsing when plan summary is not found."""
    log_text = "Some terraform output without plan summary"
    result = _parse_terraform_log(log_text, "plan")
    assert result == "Terraform plan ran, but summary line could not be found in logs."

def test_parse_terraform_log_apply_success():
    """Tests parsing of terraform apply logs."""
    log_text = 'service_url = "https://my-service-123-uc.a.run.app"'
    result = _parse_terraform_log(log_text, "apply -auto-approve")
    assert result == "Terraform apply complete. New service URL: https://my-service-123-uc.a.run.app"

def test_parse_terraform_log_apply_alternative_format():
    """Tests parsing apply logs with alternative URL format."""
    log_text = 'service_url = https://my-service-456-uc.a.run.app'
    result = _parse_terraform_log(log_text, "apply -auto-approve")
    assert result == "Terraform apply complete. New service URL: https://my-service-456-uc.a.run.app"

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