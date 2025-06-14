# tests/test_rollback_agent.py

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

# Adjust the path to find your agent files
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'multi_tool_agent')))

from rollback_agent import get_previous_stable_revision, redirect_traffic_to_revision

@pytest.fixture
def mock_revisions_client(mocker):
    """Mocks the google.cloud.run_v2.RevisionsClient."""
    mock_client_class = mocker.patch('rollback_agent.run_v2.RevisionsClient')
    mock_client_instance = MagicMock()
    mock_client_class.return_value = mock_client_instance
    return mock_client_instance

@pytest.fixture
def mock_services_client(mocker):
    """Mocks the google.cloud.run_v2.ServicesClient."""
    mock_client_class = mocker.patch('rollback_agent.run_v2.ServicesClient')
    mock_client_instance = MagicMock()
    mock_client_class.return_value = mock_client_instance
    return mock_client_instance

def test_get_previous_stable_revision_success(mock_revisions_client):
    """Tests finding a stable revision when at least two revisions exist."""
    # --- Mock Setup ---
    # Create mock revision objects. Sorting depends on create_time.
    mock_rev_1_old = MagicMock()
    mock_rev_1_old.name = "projects/p/locations/l/services/s/revisions/rev-00001"
    mock_rev_1_old.create_time = datetime(2025, 6, 1, 10, 0, 0, tzinfo=timezone.utc)

    mock_rev_2_new = MagicMock()
    mock_rev_2_new.name = "projects/p/locations/l/services/s/revisions/rev-00002"
    mock_rev_2_new.create_time = datetime(2025, 6, 1, 11, 0, 0, tzinfo=timezone.utc)
    
    mock_revisions_client.list_revisions.return_value = [mock_rev_1_old, mock_rev_2_new]

    # --- Function Call ---
    result = get_previous_stable_revision("p", "l", "s")

    # --- Assertions ---
    assert result["status"] == "SUCCESS"
    # The function sorts by create_time descending, so rev-00001 should be the "previous" one
    assert result["previous_stable_revision_name"] == "projects/p/locations/l/services/s/revisions/rev-00001"
    assert "Identified previous stable revision" in result["message"]

def test_get_previous_stable_revision_insufficient_revisions(mock_revisions_client):
    """Tests the case where there is only one revision, so no rollback is possible."""
    # --- Mock Setup ---
    mock_rev_1 = MagicMock()
    mock_revisions_client.list_revisions.return_value = [mock_rev_1]
    
    # --- Function Call ---
    result = get_previous_stable_revision("p", "l", "s")

    # --- Assertions ---
    assert result["status"] == "FAILURE"
    assert "Fewer than two revisions exist" in result["error_message"]

def test_redirect_traffic_to_revision_success(mock_services_client):
    """Tests the successful redirection of traffic to a specified revision."""
    # --- Mock Setup ---
    # Mock the update_service call to return a mock LRO that completes successfully
    mock_operation = MagicMock()
    mock_operation.result.return_value = MagicMock() # Simulate a successful wait
    mock_services_client.update_service.return_value = mock_operation
    
    # --- Function Call ---
    result = redirect_traffic_to_revision(
        project_id="p",
        location="l",
        service_id="s",
        revision_name="projects/p/locations/l/services/s/revisions/rev-to-restore"
    )

    # --- Assertions ---
    assert result["status"] == "SUCCESS"
    assert "Successfully rolled back" in result["message"]
    mock_services_client.update_service.assert_called_once()
    # Check that the traffic target was configured correctly in the call
    called_service_config = mock_services_client.update_service.call_args[1]['service']
    assert len(called_service_config.traffic) == 1
    assert called_service_config.traffic[0].revision == "projects/p/locations/l/services/s/revisions/rev-to-restore"
    assert called_service_config.traffic[0].percent == 100