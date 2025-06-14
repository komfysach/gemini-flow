# tests/test_bta_agent.py

import pytest
from unittest.mock import MagicMock, patch

# Adjust the path to find your agent files
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'multi_tool_agent')))

from google.cloud.devtools import cloudbuild_v1
from bta_agent import trigger_build_and_monitor

# A fixture to provide a mock CloudBuildClient
@pytest.fixture
def mock_cloud_build_client(mocker):
    """Mocks the google.cloud.devtools.cloudbuild_v1.CloudBuildClient."""
    mock_client_class = mocker.patch('bta_agent.cloudbuild_v1.CloudBuildClient')
    mock_client_instance = MagicMock()
    mock_client_class.return_value = mock_client_instance
    return mock_client_instance

def test_trigger_build_success_with_passing_tests(mocker, mock_cloud_build_client):
    """
    Tests the happy path: build succeeds, test artifact is found, and all tests passed.
    """
    # --- Mock Setup ---
    # MODIFIED: Provide a valid bucket name for the test run to prevent exceptions.
    mocker.patch('bta_agent.TEST_RESULTS_BUCKET_NAME', 'mock-bucket-name-for-tests')

    # Mock the return value of the build operation
    mock_build_result = MagicMock()
    mock_build_result.status = cloudbuild_v1.Build.Status.SUCCESS # Use the enum for clarity
    mock_build_result.id = "mock_build_id_123"
    mock_build_result.log_url = "[http://logs.example.com/123](http://logs.example.com/123)"
    
    mock_operation = MagicMock()
    mock_operation.result.return_value = mock_build_result
    mock_cloud_build_client.run_build_trigger.return_value = mock_operation
    
    # Mock MessageToDict to return the correct structure for the 'details' object
    mock_details_dict = {
        "results": {
            "images": [
                {"name": "us-central1-docker.pkg.dev/proj/repo/img:tag", "digest": "sha256:abc"}
            ]
        }
    }
    mocker.patch('bta_agent.MessageToDict', return_value=mock_details_dict)
    
    # Mock the helper functions for downloading and parsing test results
    mocker.patch('bta_agent._download_gcs_artifact', return_value='{"Action":"pass"}') # Simulate non-empty JSON
    mocker.patch('bta_agent._parse_go_test_json', return_value={
        "tests": 5, "failures": 0, "skipped": 0, "failure_details": []
    })
    mocker.patch('bta_agent._summarize_test_failures_with_gemini', return_value="All tests passed.")
    
    # --- Function Call ---
    result = trigger_build_and_monitor(
        trigger_id="test-trigger",
        project_id="test-project",
        repo_name="test-repo",
        branch_name="main",
        commit_sha="abcdef12345"
    )

    # --- Assertions ---
    assert result["status"] == "SUCCESS"
    assert result["message"] == "Build completed successfully."
    assert result["test_results"]["test_status"] == "PASSED"
    assert result["test_results"]["tests_run"] == 5
    assert result["test_results"]["tests_failed"] == 0
    assert "All tests passed" in result["test_results"]["failure_summary"]

def test_trigger_build_success_with_failing_tests(mocker, mock_cloud_build_client):
    """
    Tests the path where the build succeeds, but some tests fail.
    """
    # --- Mock Setup ---
    mocker.patch('bta_agent.TEST_RESULTS_BUCKET_NAME', 'mock-bucket-name-for-tests')
    mocker.patch('bta_agent._download_gcs_artifact', return_value='{"Action":"fail"}')
    mocker.patch('bta_agent._parse_go_test_json', return_value={
        "tests": 5, "failures": 1, "failure_details": [{"test_name": "TestFailing", "details": "Expected true, got false"}]
    })
    mocker.patch('bta_agent._summarize_test_failures_with_gemini', return_value="Gemini summary of the failure.")

    mock_build_result = MagicMock()
    mock_build_result.status = cloudbuild_v1.Build.Status.SUCCESS
    mock_operation = MagicMock()
    mock_operation.result.return_value = mock_build_result
    mock_cloud_build_client.run_build_trigger.return_value = mock_operation

    # --- Function Call ---
    result = trigger_build_and_monitor("t", "p", "r", "b", "c")

    # --- Assertions ---
    assert result["status"] == "SUCCESS"
    assert result["test_results"]["test_status"] == "FAILED"
    assert result["test_results"]["tests_failed"] == 1
    assert "Gemini summary" in result["test_results"]["failure_summary"]


def test_trigger_build_fails(mocker, mock_cloud_build_client):
    """
    Tests the path where the Cloud Build job itself fails.
    """
    # --- Mock Setup ---
    mocker.patch('bta_agent.TEST_RESULTS_BUCKET_NAME', 'mock-bucket-name-for-tests')
    
    mock_build_result = MagicMock()
    mock_build_result.status = cloudbuild_v1.Build.Status.FAILURE # Simulate a build failure
    mock_build_result.id = "mock_build_id_fail"
    mock_build_result.log_url = "[http://logs.example.com/fail](http://logs.example.com/fail)"
    mock_operation = MagicMock()
    mock_operation.result.return_value = mock_build_result
    mock_cloud_build_client.run_build_trigger.return_value = mock_operation

    mocker.patch('bta_agent._download_gcs_artifact', return_value=None)
    
    # --- Function Call ---
    result = trigger_build_and_monitor("t", "p", "r", "b", "c")

    # --- Assertions ---
    assert result["status"] == "FAILURE" # MODIFIED: The test should expect 'FAILURE'
    assert "failed with status FAILURE" in result["error_message"]
    assert result["test_results"]["test_status"] == "RESULTS_FILE_NOT_FOUND"