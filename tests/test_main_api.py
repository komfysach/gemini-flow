# tests/test_main_api.py

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

# Adjust the path to find your agent files
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'multi_tool_agent')))

# We need to mock the moa_agent *before* it's imported by the API
# This fixture handles that setup.
@pytest.fixture(scope="module")
def mock_moa_agent():
    with patch('main_api.moa_agent', new_callable=MagicMock) as mock_agent:
        yield mock_agent

# Now we can import the app, which will use our mocked agent
from main_api import app

# Create a TestClient instance for making API requests
client = TestClient(app)

def test_invoke_agent_success(mock_moa_agent):
    """
    Tests the /invoke endpoint for a successful agent interaction.
    """
    # --- Mock Setup ---
    # Configure our mocked MOA to return a specific dictionary when invoke is called
    mock_response = {
        "text": "Deployment complete.",
        "tool_response": "Workflow summary..."
    }
    mock_moa_agent.invoke.return_value = mock_response

    # --- API Call ---
    # Use the TestClient to send a POST request to the /invoke endpoint
    response = client.post("/invoke", json={"query": "deploy the app"})

    # --- Assertions ---
    assert response.status_code == 200
    response_json = response.json()
    assert "response" in response_json
    # Check that the API correctly combined the text and tool_response
    assert "Deployment complete." in response_json["response"]
    assert "Workflow summary..." in response_json["response"]
    # Verify that the agent's invoke method was called with the correct data
    mock_moa_agent.invoke.assert_called_once_with({"text": "deploy the app"})

def test_invoke_agent_raises_exception(mock_moa_agent):
    """
    Tests that the /invoke endpoint returns a 500 error if the agent raises an exception.
    """
    # --- Mock Setup ---
    # Configure the mock to raise an exception when called
    mock_moa_agent.invoke.side_effect = Exception("A critical agent error occurred")

    # --- API Call ---
    response = client.post("/invoke", json={"query": "deploy the app"})

    # --- Assertions ---
    assert response.status_code == 500
    response_json = response.json()
    assert "detail" in response_json
    assert "A critical agent error occurred" in response_json["detail"]

def test_read_root():
    """
    Tests the root endpoint ('/'). It should return the index.html file.
    We can't easily test the file content without more setup, so we'll check for a successful
    status code and that the content type is HTML.
    """
    # --- API Call ---
    response = client.get("/")

    # --- Assertions ---
    assert response.status_code == 200
    assert response.headers['content-type'] == 'text/html; charset=utf-8'