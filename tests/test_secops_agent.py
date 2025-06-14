# tests/test_secops_agent.py

import pytest
from unittest.mock import MagicMock, patch

# Adjust the path to find your agent files
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'multi_tool_agent')))

# Import the functions and classes to be tested/mocked
from secops_agent import get_vulnerability_scan_results, summarize_vulnerabilities_with_gemini

@pytest.fixture
def mock_container_analysis_client(mocker):
    """Mocks the google.cloud.containeranalysis_v1.ContainerAnalysisClient."""
    mock_client_class = mocker.patch('secops_agent.containeranalysis_v1.ContainerAnalysisClient')
    mock_client_instance = MagicMock()
    mock_grafeas_client = MagicMock()
    mock_client_instance.get_grafeas_client.return_value = mock_grafeas_client
    mock_client_class.return_value = mock_client_instance
    return mock_grafeas_client

@pytest.fixture
def mock_gemini_model(mocker):
    """Mocks the google.generativeai.GenerativeModel."""
    mock_model_class = mocker.patch('secops_agent.genai.GenerativeModel')
    mock_model_instance = MagicMock()
    mock_model_class.return_value = mock_model_instance
    return mock_model_instance

def test_get_vulnerability_scan_results_success(mocker, mock_container_analysis_client):
    """Tests the happy path where vulnerabilities are found."""
    # --- Mock Setup ---
    mocker.patch('secops_agent.GCP_PROJECT_ID', 'test-project')

    # Simulate a vulnerability occurrence from the API
    mock_occurrence = MagicMock()
    
    # Mock the vulnerability object structure - no Severity conversion needed
    mock_vulnerability = MagicMock()
    mock_vulnerability.severity = "CRITICAL"  # Direct string value
    mock_vulnerability.cvss_score = 9.8
    mock_vulnerability.short_description = "CVE-2024-12345 in lib-a"
    
    # Mock package issue
    mock_package_issue = MagicMock()
    mock_package_issue.affected_package = "lib-a"
    mock_affected_version = MagicMock()
    mock_affected_version.full_name = "1.2.3"
    mock_package_issue.affected_version = mock_affected_version
    mock_vulnerability.package_issue = [mock_package_issue]
    
    mock_occurrence.vulnerability = mock_vulnerability
    
    # Configure the mocked client to return our mock occurrence
    mock_container_analysis_client.list_occurrences.return_value = [mock_occurrence]

    # --- Function Call ---
    result = get_vulnerability_scan_results("us-central1-docker.pkg.dev/test/repo/image@sha256:abc123")

    # --- Assertions ---
    assert result["status"] == "SUCCESS"
    assert result["vulnerability_count"] == 1
    vuln = result["vulnerabilities"][0]
    assert vuln["severity"] == "CRITICAL"
    assert vuln["package"] == "lib-a"
    assert vuln["version"] == "1.2.3"
    assert vuln["cvss_score"] == 9.8
    assert "CVE-2024-12345" in vuln["description"]
    assert vuln["cve"] == "CVE-2024-12345"

def test_get_vulnerability_scan_results_multiple_vulnerabilities(mocker, mock_container_analysis_client):
    """Tests the path where multiple vulnerabilities are found."""
    # --- Mock Setup ---
    mocker.patch('secops_agent.GCP_PROJECT_ID', 'test-project')

    # Create multiple mock occurrences
    mock_occurrence1 = MagicMock()
    mock_vulnerability1 = MagicMock()
    mock_vulnerability1.severity = "CRITICAL"
    mock_vulnerability1.cvss_score = 9.8
    mock_vulnerability1.short_description = "CVE-2024-12345 in lib-a"
    mock_package_issue1 = MagicMock()
    mock_package_issue1.affected_package = "lib-a"
    mock_package_issue1.affected_version.full_name = "1.2.3"
    mock_vulnerability1.package_issue = [mock_package_issue1]
    mock_occurrence1.vulnerability = mock_vulnerability1

    mock_occurrence2 = MagicMock()
    mock_vulnerability2 = MagicMock()
    mock_vulnerability2.severity = "HIGH"
    mock_vulnerability2.cvss_score = 7.5
    mock_vulnerability2.short_description = "CVE-2024-67890 in lib-b"
    mock_package_issue2 = MagicMock()
    mock_package_issue2.affected_package = "lib-b"
    mock_package_issue2.affected_version.full_name = "2.1.0"
    mock_vulnerability2.package_issue = [mock_package_issue2]
    mock_occurrence2.vulnerability = mock_vulnerability2
    
    # Configure the mocked client to return both occurrences
    mock_container_analysis_client.list_occurrences.return_value = [mock_occurrence1, mock_occurrence2]

    # --- Function Call ---
    result = get_vulnerability_scan_results("us-central1-docker.pkg.dev/test/repo/image@sha256:abc123")

    # --- Assertions ---
    assert result["status"] == "SUCCESS"
    assert result["vulnerability_count"] == 2
    assert len(result["vulnerabilities"]) == 2
    
    # Check first vulnerability
    vuln1 = result["vulnerabilities"][0]
    assert vuln1["severity"] == "CRITICAL"
    assert vuln1["package"] == "lib-a"
    assert vuln1["cvss_score"] == 9.8
    
    # Check second vulnerability
    vuln2 = result["vulnerabilities"][1]
    assert vuln2["severity"] == "HIGH"
    assert vuln2["package"] == "lib-b"
    assert vuln2["cvss_score"] == 7.5

def test_get_vulnerability_scan_results_no_package_issue(mocker, mock_container_analysis_client):
    """Tests vulnerability with no package issue (edge case)."""
    # --- Mock Setup ---
    mocker.patch('secops_agent.GCP_PROJECT_ID', 'test-project')

    mock_occurrence = MagicMock()
    mock_vulnerability = MagicMock()
    mock_vulnerability.severity = "MEDIUM"
    mock_vulnerability.cvss_score = 5.0
    mock_vulnerability.short_description = "CVE-2024-99999 unknown package"
    mock_vulnerability.package_issue = []  # Empty package issue list
    mock_occurrence.vulnerability = mock_vulnerability
    
    mock_container_analysis_client.list_occurrences.return_value = [mock_occurrence]

    # --- Function Call ---
    result = get_vulnerability_scan_results("us-central1-docker.pkg.dev/test/repo/image@sha256:abc123")

    # --- Assertions ---
    assert result["status"] == "SUCCESS"
    assert result["vulnerability_count"] == 1
    vuln = result["vulnerabilities"][0]
    assert vuln["severity"] == "MEDIUM"
    assert vuln["package"] == "N/A"  # Should default to N/A when no package issue
    assert vuln["version"] == "N/A"  # Should default to N/A when no package issue
    assert vuln["cvss_score"] == 5.0

def test_get_vulnerability_scan_results_no_vulns(mocker, mock_container_analysis_client):
    """Tests the path where no vulnerabilities are found."""
    # --- Mock Setup ---
    mocker.patch('secops_agent.GCP_PROJECT_ID', 'test-project')
    mock_container_analysis_client.list_occurrences.return_value = []
    mocker.patch('secops_agent.time.sleep')  # Mock sleep to speed up test

    # --- Function Call ---
    result = get_vulnerability_scan_results("us-central1-docker.pkg.dev/test/repo/image@sha256:clean")
    
    # --- Assertions ---
    assert result["status"] == "SUCCESS"
    assert result["vulnerability_count"] == 0
    assert result["vulnerabilities"] == []
    assert mock_container_analysis_client.list_occurrences.call_count == 3  # Retries 3 times

def test_get_vulnerability_scan_results_invalid_image_uri(mocker):
    """Tests handling of invalid image URI."""
    mocker.patch('secops_agent.GCP_PROJECT_ID', 'test-project')
    
    # --- Function Call with invalid URI (no digest) ---
    result = get_vulnerability_scan_results("us-central1-docker.pkg.dev/test/repo/image:latest")
    
    # --- Assertions ---
    assert result["status"] == "ERROR"
    assert "Invalid image URI" in result["error_message"]
    assert "Must include a sha256 digest" in result["error_message"]

def test_get_vulnerability_scan_results_no_project_id(mocker):
    """Tests handling when GCP_PROJECT_ID is not set."""
    mocker.patch('secops_agent.GCP_PROJECT_ID', None)
    
    # --- Function Call ---
    result = get_vulnerability_scan_results("us-central1-docker.pkg.dev/test/repo/image@sha256:abc123")
    
    # --- Assertions ---
    assert result["status"] == "ERROR"
    assert "GCP_PROJECT_ID environment variable not set" in result["error_message"]

def test_get_vulnerability_scan_results_api_error(mocker, mock_container_analysis_client):
    """Tests handling of API errors."""
    # --- Mock Setup ---
    mocker.patch('secops_agent.GCP_PROJECT_ID', 'test-project')
    mock_container_analysis_client.list_occurrences.side_effect = Exception("API Error")

    # --- Function Call ---
    result = get_vulnerability_scan_results("us-central1-docker.pkg.dev/test/repo/image@sha256:abc123")
    
    # --- Assertions ---
    assert result["status"] == "ERROR"
    assert "Error querying Artifact Analysis API" in result["error_message"]
    assert "API Error" in result["error_message"]

def test_summarize_vulnerabilities_with_gemini_success(mock_gemini_model):
    """Tests that Gemini is called correctly to summarize results."""
    # --- Mock Setup ---
    mock_response = MagicMock()
    mock_response.text = "This is a mock Gemini summary with security recommendations."
    mock_gemini_model.generate_content.return_value = mock_response
    
    mock_scan_results = {
        "status": "SUCCESS",
        "vulnerabilities": [
            {
                "severity": "CRITICAL", 
                "cvss_score": 9.8, 
                "package": "lib-a", 
                "version": "1.2.3", 
                "cve": "CVE-2024-12345",
                "description": "CVE-2024-12345 in lib-a"
            }
        ]
    }

    # --- Function Call ---
    summary = summarize_vulnerabilities_with_gemini(mock_scan_results)

    # --- Assertions ---
    assert "Security Scan Summary:" in summary
    assert "This is a mock Gemini summary with security recommendations." in summary
    mock_gemini_model.generate_content.assert_called_once()
    
    # Check that the prompt contains the vulnerability details
    prompt_sent = mock_gemini_model.generate_content.call_args[0][0]
    assert "CRITICAL" in prompt_sent
    assert "CVE-2024-12345" in prompt_sent
    assert "lib-a" in prompt_sent
    assert "9.8" in prompt_sent

def test_summarize_vulnerabilities_with_gemini_no_vulns():
    """Tests summarization when no vulnerabilities are found."""
    mock_scan_results = {
        "status": "SUCCESS",
        "vulnerabilities": []
    }

    # --- Function Call ---
    summary = summarize_vulnerabilities_with_gemini(mock_scan_results)

    # --- Assertions ---
    assert "No vulnerabilities were found" in summary
    assert "image is considered clean" in summary

def test_summarize_vulnerabilities_with_gemini_scan_failed():
    """Tests summarization when the scan failed."""
    mock_scan_results = {
        "status": "ERROR",
        "error_message": "Scan failed"
    }

    # --- Function Call ---
    summary = summarize_vulnerabilities_with_gemini(mock_scan_results)

    # --- Assertions ---
    assert "Could not generate summary" in summary
    assert "did not complete successfully" in summary

def test_summarize_vulnerabilities_with_gemini_api_error(mock_gemini_model):
    """Tests handling of Gemini API errors."""
    # --- Mock Setup ---
    mock_gemini_model.generate_content.side_effect = Exception("Gemini API Error")
    
    mock_scan_results = {
        "status": "SUCCESS",
        "vulnerabilities": [
            {
                "severity": "HIGH", 
                "cvss_score": 7.5, 
                "package": "lib-b", 
                "version": "2.1.0", 
                "cve": "CVE-2024-67890",
                "description": "CVE-2024-67890 in lib-b"
            }
        ]
    }

    # --- Function Call ---
    summary = summarize_vulnerabilities_with_gemini(mock_scan_results)

    # --- Assertions ---
    assert "Could not summarize vulnerabilities due to an error" in summary
    assert "Found 1 vulnerabilities" in summary