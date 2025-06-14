# tests/test_agent.py

import pytest
from unittest.mock import patch

# Adjust the path to find your agent files
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'multi_tool_agent')))

# Import the tool functions from the main agent.py to be tested
from agent import execute_smart_deploy_workflow, execute_health_check_workflow

# We will mock the functions that these tools call.
# The paths for patching are relative to where they are imported in 'agent.py'.
SCA_LATEST_COMMIT = 'agent.get_latest_commit_sha'
BTA_TRIGGER_BUILD = 'agent.trigger_build_and_monitor'
SECOPS_GET_RESULTS = 'agent.get_vulnerability_scan_results'
SECOPS_SUMMARIZE = 'agent.summarize_vulnerabilities_with_gemini'
DA_DEPLOY = 'agent.deploy_to_cloud_run'
MDA_GET_METRICS = 'agent.get_cloud_run_metrics'
MDA_GET_LOGS = 'agent.get_cloud_run_logs'
MDA_GENERATE_REPORT = 'agent.generate_health_report'


@patch(DA_DEPLOY)
@patch(SECOPS_SUMMARIZE)
@patch(SECOPS_GET_RESULTS)
@patch(BTA_TRIGGER_BUILD)
@patch(SCA_LATEST_COMMIT)
def test_smart_deploy_workflow_success_path(
    mock_sca_commit, mock_bta_build, mock_secops_scan, mock_secops_summary, mock_da_deploy
):
    """
    Tests the full "happy path" of the smart deploy workflow where all steps succeed.
    """
    # --- Mock Setup ---
    # Configure mocks to return successful dictionaries for each step
    mock_sca_commit.return_value = {"status": "SUCCESS", "commit_sha": "abcdef123", "message": "SCA success"}
    
    mock_bta_build.return_value = {
        "status": "SUCCESS",
        "message": "BTA success",
        "image_uri_commit": "gcr.io/proj/img:abcdef123",
        "details": {"results": {"images": [{"name": "gcr.io/proj/img:abcdef123", "digest": "sha256:digest123"}]}},
        "test_results": {"test_status": "PASSED", "failure_summary": "All tests passed."}
    }

    mock_secops_scan.return_value = {"status": "SUCCESS", "vulnerabilities": []}
    mock_secops_summary.return_value = "Security Scan Summary: No vulnerabilities were found."
    
    mock_da_deploy.return_value = {"status": "SUCCESS", "message": "DA success", "service_url": "[http://service.url](http://service.url)"}

    # --- Function Call ---
    result = execute_smart_deploy_workflow("gemini-flow-hello-world", "main")

    # --- Assertions ---
    assert "1. SCA Report: SCA success" in result
    assert "2. BTA Report: BTA success" in result
    assert "Test Status: All tests passed" in result
    # MODIFIED: Corrected the assertion to match the actual output format
    assert "3. Security Scan Summary: No vulnerabilities were found." in result
    assert "4. Deployment: DA success" in result
    # Check that all mocked functions were called once
    mock_sca_commit.assert_called_once()
    mock_bta_build.assert_called_once()
    mock_secops_scan.assert_called_once()
    mock_secops_summary.assert_called_once()
    mock_da_deploy.assert_called_once()


@patch(BTA_TRIGGER_BUILD)
@patch(SCA_LATEST_COMMIT)
def test_smart_deploy_workflow_bta_failure(mock_sca_commit, mock_bta_build):
    """
    Tests that the workflow halts correctly if the BTA step fails.
    """
    # --- Mock Setup ---
    mock_sca_commit.return_value = {"status": "SUCCESS", "commit_sha": "abcdef123", "message": "SCA success"}
    mock_bta_build.return_value = {"status": "FAILURE", "error_message": "Build failed in tests"}

    # --- Function Call ---
    result = execute_smart_deploy_workflow("gemini-flow-hello-world", "main")
    
    # --- Assertions ---
    assert "2. BTA Report: Build failed in tests" in result
    assert "3. Security Scan" not in result # Verify the next step was not reached


@patch(MDA_GENERATE_REPORT)
@patch(MDA_GET_LOGS)
@patch(MDA_GET_METRICS)
def test_health_check_workflow_success(mock_get_metrics, mock_get_logs, mock_generate_report):
    """Tests that the health check workflow correctly calls all MDA functions."""
    # --- Mock Setup ---
    mock_get_metrics.return_value = {"status": "SUCCESS", "metrics": {"request_count": 100}}
    mock_get_logs.return_value = {"status": "SUCCESS", "log_entries": ["log1"]}
    mock_generate_report.return_value = "Formatted raw health data"
    
    # --- Function Call ---
    result = execute_health_check_workflow(
        service_id="test-svc",
        location="us-central1"
    )

    # --- Assertions ---
    assert result == "Formatted raw health data"
    mock_get_metrics.assert_called_once()
    mock_get_logs.assert_called_once()
    mock_generate_report.assert_called_once()