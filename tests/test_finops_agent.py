# tests/test_finops_agent.py

import pytest
from unittest.mock import MagicMock, patch

# Adjust the path to find your agent files
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'multi_tool_agent')))

from finops_agent import get_total_project_cost, get_cost_by_service

@pytest.fixture
def mock_bigquery_client(mocker):
    """Mocks the google.cloud.bigquery.Client."""
    mock_client_class = mocker.patch('finops_agent.bigquery.Client')
    mock_client_instance = MagicMock()
    mock_client_class.return_value = mock_client_instance
    return mock_client_instance

def test_get_total_project_cost_success(mocker, mock_bigquery_client):
    """Tests the successful calculation of total project cost."""
    # --- Mock Setup ---
    # MODIFIED: Patch the module-level variables directly
    mocker.patch('finops_agent.BIGQUERY_BILLING_TABLE', 'mock.billing.table')
    mocker.patch('finops_agent.GCP_PROJECT_ID', 'test-project')
    
    # Simulate the BigQuery result
    mock_row = MagicMock()
    mock_row.total_cost = 123.45
    mock_query_job = MagicMock()
    mock_query_job.result.return_value = [mock_row]
    mock_bigquery_client.query.return_value = mock_query_job
    
    # --- Function Call ---
    result = get_total_project_cost(days_ago=10)

    # --- Assertions ---
    assert result["status"] == "SUCCESS"
    assert result["total_cost"] == "$123.45"
    assert "Total cost for project 'test-project' over the last 10 days" in result["message"]
    mock_bigquery_client.query.assert_called_once()

def test_get_cost_by_service_success(mocker, mock_bigquery_client):
    """Tests the successful retrieval of costs broken down by service."""
    # --- Mock Setup ---
    # MODIFIED: Patch the module-level variables directly
    mocker.patch('finops_agent.BIGQUERY_BILLING_TABLE', 'mock.billing.table')
    mocker.patch('finops_agent.GCP_PROJECT_ID', 'test-project')

    # Simulate the BigQuery result with multiple rows
    mock_row1 = MagicMock()
    mock_row1.service_name = "Cloud Run"
    mock_row1.total_cost = 50.25
    mock_row2 = MagicMock()
    mock_row2.service_name = "Cloud Build"
    mock_row2.total_cost = 25.50
    
    mock_query_job = MagicMock()
    mock_query_job.result.return_value = [mock_row1, mock_row2]
    mock_bigquery_client.query.return_value = mock_query_job
    
    # --- Function Call ---
    result = get_cost_by_service(days_ago=10, limit=2)

    # --- Assertions ---
    assert result["status"] == "SUCCESS"
    assert len(result["cost_breakdown"]) == 2
    assert result["cost_breakdown"][0]["service_name"] == "Cloud Run"
    assert result["cost_breakdown"][0]["total_cost"] == "$50.25"
    assert result["cost_breakdown"][1]["service_name"] == "Cloud Build"
    assert result["cost_breakdown"][1]["total_cost"] == "$25.50"
    mock_bigquery_client.query.assert_called_once()


def test_get_total_project_cost_no_config(mocker):
    """Tests that the cost functions fail gracefully if config is missing."""
    # MODIFIED: Patch the module-level variable to the specific default value
    # that the function checks against to trigger the error.
    mocker.patch('finops_agent.BIGQUERY_BILLING_TABLE', "your-project.your_dataset.gcp_billing_export_v1_XXXX")
    
    result = get_total_project_cost()
    
    assert result["status"] == "ERROR"
    assert "BIGQUERY_BILLING_TABLE environment variable not set" in result["error_message"]