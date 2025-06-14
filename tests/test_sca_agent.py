# tests/test_sca_agent.py

import pytest
from unittest.mock import MagicMock, patch

# To allow pytest to find your agent files, we might need to adjust the path.
# This assumes your 'multi_tool_agent' directory is at the same level as 'tests/'
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'multi_tool_agent')))

# Now you can import the function to be tested
from sca_agent import get_latest_commit_sha

# A "fixture" is a reusable setup function for tests. Pytest handles them automatically.
# This fixture provides a mock Github object for our tests.
@pytest.fixture
def mock_github_client(mocker):
    """Mocks the github.Github client."""
    # Create a mock for the entire 'github' module that sca_agent will import
    mock_github_module = mocker.patch('sca_agent.Github')

    # Create mock objects for the chain of calls: repo -> branch -> commit -> sha
    mock_commit = MagicMock()
    mock_commit.sha = "mock_commit_sha_12345"

    mock_branch = MagicMock()
    mock_branch.commit = mock_commit

    mock_repo = MagicMock()
    mock_repo.get_branch.return_value = mock_branch

    # Configure the Github client instance to return our mock repo
    mock_github_instance = MagicMock()
    mock_github_instance.get_repo.return_value = mock_repo
    
    # Make the Github() constructor return our mock instance
    mock_github_module.return_value = mock_github_instance
    
    return mock_github_instance


def test_get_latest_commit_sha_success(mocker, mock_github_client):
    """
    Tests the successful path of get_latest_commit_sha.
    """
    # Set the GITHUB_PAT environment variable for the test
    mocker.patch('sca_agent.GITHUB_TOKEN', "fake_token_for_test")

    # Call the function we want to test
    result = get_latest_commit_sha(
        repo_full_name="test/repo",
        branch_name="main"
    )

    # Assertions: Check if the function behaved as expected
    assert result["status"] == "SUCCESS"
    assert result["commit_sha"] == "mock_commit_sha_12345"
    assert "Successfully fetched latest commit SHA" in result["message"]

    # Verify that the mock Github client was called correctly
    mock_github_client.get_repo.assert_called_once_with("test/repo")
    mock_github_client.get_repo.return_value.get_branch.assert_called_once_with(branch="main")


def test_get_latest_commit_sha_no_pat(mocker):
    """
    Tests that the function returns an error if the GITHUB_PAT is not set.
    """
    # We patch the GITHUB_TOKEN variable directly in the sca_agent module
    # This correctly simulates the variable being None when the function runs.
    mocker.patch('sca_agent.GITHUB_TOKEN', None)

    result = get_latest_commit_sha(
        repo_full_name="test/repo",
        branch_name="main"
    )

    # Assertions
    assert result["status"] == "ERROR"
    # MODIFIED: Changed the assertion to check for a substring that is
    # verifiably in the actual error message.
    assert "Personal Access Token" in result["error_message"]
    assert "not configured" in result["error_message"]


def test_get_latest_commit_sha_repo_not_found(mocker, mock_github_client):
    """
    Tests the failure path when the repository or branch is not found.
    """
    # This needs to be imported here because it's only used in this test case
    from github import UnknownObjectException

    mocker.patch('sca_agent.GITHUB_TOKEN', "fake_token_for_test")

    # Configure the mock to raise the specific exception GitHub's library would raise
    # when get_repo is called.
    mock_github_client.get_repo.side_effect = UnknownObjectException(status=404, data={}, headers={})

    result = get_latest_commit_sha(
        repo_full_name="nonexistent/repo",
        branch_name="main"
    )

    assert result["status"] == "FAILURE"
    assert "Could not find repository" in result["error_message"]
