# tests/test_bta_agent.py

import pytest
from unittest.mock import MagicMock, patch
import time

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
    mocker.patch('bta_agent.TEST_RESULTS_BUCKET_NAME', 'mock-bucket-name-for-tests')

    # Mock the build result
    mock_build_result = MagicMock()
    mock_build_result.status = cloudbuild_v1.Build.Status.SUCCESS
    mock_build_result.id = "mock_build_id_123"
    mock_build_result.log_url = "gs://test-bucket/logs/build.log"
    
    # Mock results with images
    mock_build_result.results = MagicMock()
    mock_build_result.results.images = [MagicMock()]
    mock_build_result.results.images[0].name = "us-central1-docker.pkg.dev/proj/repo/img:tag"
    mock_build_result.results.images[0].digest = "sha256:abc"
    
    # Mock the operation and get_build calls
    mock_operation = MagicMock()
    mock_operation.metadata.build.id = "mock_build_id_123"
    mock_cloud_build_client.run_build_trigger.return_value = mock_operation
    mock_cloud_build_client.get_build.return_value = mock_build_result
    
    # Mock time.sleep to avoid delays in tests
    mocker.patch('time.sleep')
    
    # Mock the helper functions for downloading and parsing test results
    mocker.patch('bta_agent._download_gcs_artifact', return_value='{"Action":"pass"}')
    mocker.patch('bta_agent._parse_go_test_json', return_value={
        "tests": 5, "failures": 0, "skipped": 0, "failure_details": []
    })
    mocker.patch('bta_agent._summarize_test_failures_with_gemini', return_value="All tests passed.")
    
    # Mock fetch_build_logs and summarize_build_logs_with_gemini
    mocker.patch('bta_agent.fetch_build_logs', return_value="Build log content")
    mocker.patch('bta_agent.summarize_build_logs_with_gemini', return_value="Build summary")
    
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
    assert "Build completed successfully" in result["message"]
    assert result["test_results"]["test_status"] == "PASSED"
    assert result["test_results"]["tests_total"] == 5
    assert result["test_results"]["tests_failed"] == 0

def test_trigger_build_success_with_failing_tests(mocker, mock_cloud_build_client):
    """
    Tests the path where the build succeeds, but some tests fail.
    """
    # --- Mock Setup ---
    mocker.patch('bta_agent.TEST_RESULTS_BUCKET_NAME', 'mock-bucket-name-for-tests')
    
    # Mock the build result
    mock_build_result = MagicMock()
    mock_build_result.status = cloudbuild_v1.Build.Status.SUCCESS
    mock_build_result.id = "mock_build_id_123"
    mock_build_result.log_url = "gs://test-bucket/logs/build.log"
    
    # Mock results with images
    mock_build_result.results = MagicMock()
    mock_build_result.results.images = [MagicMock()]
    mock_build_result.results.images[0].name = "us-central1-docker.pkg.dev/proj/repo/img:tag"
    mock_build_result.results.images[0].digest = "sha256:abc"
    
    mock_operation = MagicMock()
    mock_operation.metadata.build.id = "mock_build_id_123"
    mock_cloud_build_client.run_build_trigger.return_value = mock_operation
    mock_cloud_build_client.get_build.return_value = mock_build_result
    
    mocker.patch('time.sleep')
    mocker.patch('bta_agent._download_gcs_artifact', return_value='{"Action":"fail"}')
    mocker.patch('bta_agent._parse_go_test_json', return_value={
        "tests": 5, "failures": 1, "skipped": 0, "failure_details": [{"test_name": "TestFailing", "details": "Expected true, got false"}]
    })
    mocker.patch('bta_agent._summarize_test_failures_with_gemini', return_value="Gemini summary of the failure.")
    mocker.patch('bta_agent.fetch_build_logs', return_value="Build log content")
    mocker.patch('bta_agent.summarize_build_logs_with_gemini', return_value="Build summary")

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
    mock_build_result.status = cloudbuild_v1.Build.Status.FAILURE
    mock_build_result.id = "mock_build_id_fail"
    mock_build_result.log_url = "gs://test-bucket/logs/build.log"
    mock_build_result.failure_info = MagicMock()
    mock_build_result.failure_info.detail = "Build step failed"
    
    mock_operation = MagicMock()
    mock_operation.metadata.build.id = "mock_build_id_fail"
    mock_cloud_build_client.run_build_trigger.return_value = mock_operation
    mock_cloud_build_client.get_build.return_value = mock_build_result

    mocker.patch('time.sleep')
    mocker.patch('bta_agent._download_gcs_artifact', return_value=None)
    mocker.patch('bta_agent.extract_test_results', return_value={
        "test_status": "NO_TESTS",
        "message": "No test results found for this build."
    })
    mocker.patch('bta_agent.fetch_build_logs', return_value="Build failed log content")
    mocker.patch('bta_agent.summarize_build_logs_with_gemini', return_value="Build failure analysis")
    
    # --- Function Call ---
    result = trigger_build_and_monitor("t", "p", "r", "b", "c")

    # --- Assertions ---
    assert result["status"] == "FAILURE"
    assert "Build failed with status: FAILURE" in result["error_message"]
    assert "Build failure analysis" in result["error_message"]