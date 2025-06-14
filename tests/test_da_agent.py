import pytest
from unittest.mock import MagicMock, patch
import sys
import os

# Adjust the path to find your agent files
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'multi_tool_agent')))

from google.cloud import run_v2
from google.api_core import exceptions as api_exceptions
from da_agent import deploy_to_cloud_run

@pytest.fixture
def mock_cloud_run_client(mocker):
    """Mocks the google.cloud.run_v2.ServicesClient."""
    mock_client_class = mocker.patch('da_agent.run_v2.ServicesClient')
    mock_client_instance = MagicMock()
    mock_client_class.return_value = mock_client_instance
    return mock_client_instance

def test_deploy_to_cloud_run_missing_parameters():
    """Test that the function returns an error when required parameters are missing."""
    result = deploy_to_cloud_run(
        project_id="",
        region="us-central1",
        service_name="test-service",
        image_uri="gcr.io/project/image:tag"
    )
    
    assert result["status"] == "ERROR"
    assert "Missing required parameters" in result["error_message"]
    assert "project_id" in result["error_message"]

def test_deploy_to_cloud_run_creates_new_service(mock_cloud_run_client, mocker):
    """Tests the flow when the service does not exist and needs to be created."""
    # Mock get_service to raise NotFound, triggering the create flow
    mock_cloud_run_client.get_service.side_effect = api_exceptions.NotFound("Service not found")
    
    # Create a proper service mock with all required attributes
    mock_service = MagicMock()
    mock_service.name = "projects/test-project/locations/us-central1/services/new-service"
    mock_service.uri = "https://new-service-123-uc.a.run.app"
    
    # Mock the create_service operation
    mock_operation = MagicMock()
    mock_operation.result.return_value = mock_service
    mock_cloud_run_client.create_service.return_value = mock_operation
    
    # Mock the IAM-related methods
    mock_policy = MagicMock()
    mock_policy.bindings = []
    mock_policy.etag = b"test-etag"
    mock_cloud_run_client.get_iam_policy.return_value = mock_policy
    mock_cloud_run_client.set_iam_policy.return_value = MagicMock()
    
    # Also mock the IAM policy protobuf classes that your code uses
    mock_get_iam_request = MagicMock()
    mock_set_iam_request = MagicMock()
    mocker.patch('da_agent.iam_policy_pb2.GetIamPolicyRequest', return_value=mock_get_iam_request)
    mocker.patch('da_agent.iam_policy_pb2.SetIamPolicyRequest', return_value=mock_set_iam_request)
    mocker.patch('da_agent.policy_pb2.Binding', return_value=MagicMock())

    # Call the function
    result = deploy_to_cloud_run(
        project_id="test-project",
        region="us-central1",
        service_name="new-service",
        image_uri="gcr.io/test/image:latest"
    )

    # Debug: Print the result if it fails
    if result["status"] != "SUCCESS":
        print(f"Actual result: {result}")
        
    # Assertions
    assert result["status"] == "SUCCESS", f"Expected SUCCESS but got {result['status']}. Error: {result.get('error_message', 'No error message')}"
    assert "created successfully" in result["message"]
    assert result["service_url"] == "https://new-service-123-uc.a.run.app"
    assert result["service_name"] == "new-service"

def test_deploy_to_cloud_run_updates_existing_service(mock_cloud_run_client, mocker):
    """Tests the flow when the service already exists and needs to be updated."""
    # Mock get_service to return an existing service
    mock_existing_service = MagicMock()
    mock_existing_service.name = "projects/test-project/locations/us-central1/services/existing-service"
    mock_cloud_run_client.get_service.return_value = mock_existing_service

    # Create the updated service object
    mock_service = MagicMock()
    mock_service.name = "projects/test-project/locations/us-central1/services/existing-service"
    mock_service.uri = "https://existing-service-456-uc.a.run.app"
    
    # Mock the update_service operation
    mock_operation = MagicMock()
    mock_operation.result.return_value = mock_service
    mock_cloud_run_client.update_service.return_value = mock_operation

    # Mock the IAM-related methods
    mock_policy = MagicMock()
    mock_policy.bindings = []
    mock_policy.etag = b"test-etag"
    mock_cloud_run_client.get_iam_policy.return_value = mock_policy
    mock_cloud_run_client.set_iam_policy.return_value = MagicMock()
    
    # Also mock the IAM policy protobuf classes
    mock_get_iam_request = MagicMock()
    mock_set_iam_request = MagicMock()
    mocker.patch('da_agent.iam_policy_pb2.GetIamPolicyRequest', return_value=mock_get_iam_request)
    mocker.patch('da_agent.iam_policy_pb2.SetIamPolicyRequest', return_value=mock_set_iam_request)
    mocker.patch('da_agent.policy_pb2.Binding', return_value=MagicMock())

    # Call the function
    result = deploy_to_cloud_run(
        project_id="test-project",
        region="us-central1",
        service_name="existing-service",
        image_uri="gcr.io/test/image:new-tag"
    )

    # Debug: Print the result if it fails
    if result["status"] != "SUCCESS":
        print(f"Actual result: {result}")

    # Assertions
    assert result["status"] == "SUCCESS", f"Expected SUCCESS but got {result['status']}. Error: {result.get('error_message', 'No error message')}"
    assert "updated successfully" in result["message"]
    assert result["service_url"] == "https://existing-service-456-uc.a.run.app"
    assert result["service_name"] == "existing-service"

def test_deploy_to_cloud_run_service_already_public(mock_cloud_run_client, mocker):
    """Tests the flow when the service is already publicly accessible."""
    # Mock get_service to raise NotFound
    mock_cloud_run_client.get_service.side_effect = api_exceptions.NotFound("Service not found")
    
    # Create the service object
    mock_service = MagicMock()
    mock_service.name = "projects/test-project/locations/us-central1/services/public-service"
    mock_service.uri = "https://public-service-789-uc.a.run.app"
    
    # Mock the create_service operation
    mock_operation = MagicMock()
    mock_operation.result.return_value = mock_service
    mock_cloud_run_client.create_service.return_value = mock_operation
    
    # Mock IAM policy that already has public access
    mock_policy = MagicMock()
    mock_binding = MagicMock()
    mock_binding.role = "roles/run.invoker"
    mock_binding.members = ["allUsers"]
    mock_policy.bindings = [mock_binding]
    mock_policy.etag = b"test-etag"
    mock_cloud_run_client.get_iam_policy.return_value = mock_policy
    
    # Mock the protobuf classes
    mocker.patch('da_agent.iam_policy_pb2.GetIamPolicyRequest', return_value=MagicMock())

    # Call the function
    result = deploy_to_cloud_run(
        project_id="test-project",
        region="us-central1",
        service_name="public-service",
        image_uri="gcr.io/test/image:latest"
    )

    # Assertions
    assert result["status"] == "SUCCESS"
    assert "created successfully" in result["message"]
    assert result["service_url"] == "https://public-service-789-uc.a.run.app"
    # Should not call set_iam_policy since already public
    mock_cloud_run_client.set_iam_policy.assert_not_called()

def test_deploy_to_cloud_run_permission_denied_error(mock_cloud_run_client):
    """Tests handling of permission denied errors."""
    # Mock get_service to raise PermissionDenied
    mock_cloud_run_client.get_service.side_effect = api_exceptions.PermissionDenied("403 Permission denied")

    # Call the function
    result = deploy_to_cloud_run(
        project_id="test-project",
        region="us-central1",
        service_name="test-service",
        image_uri="gcr.io/test/image:latest"
    )

    # Assertions
    assert result["status"] == "FAILURE"
    assert result["service_name"] == "test-service"
    # Check for the actual error message format from your code
    assert "Error during service existence check or initial operation" in result["error_message"]
    assert "403 Permission denied" in result["error_message"]

def test_deploy_to_cloud_run_operation_timeout(mock_cloud_run_client):
    """Tests handling of operation timeout."""
    # Mock get_service to raise NotFound
    mock_cloud_run_client.get_service.side_effect = api_exceptions.NotFound("Service not found")
    
    # Mock the create_service operation to timeout
    mock_operation = MagicMock()
    mock_operation.result.side_effect = Exception("Operation timed out after 600 seconds")
    mock_cloud_run_client.create_service.return_value = mock_operation

    # Call the function
    result = deploy_to_cloud_run(
        project_id="test-project",
        region="us-central1",
        service_name="timeout-service",
        image_uri="gcr.io/test/image:latest"
    )

    # Assertions
    assert result["status"] == "FAILURE"
    assert result["service_name"] == "timeout-service"
    assert "An unexpected error occurred" in result["error_message"]
    assert "Operation timed out" in result["error_message"]