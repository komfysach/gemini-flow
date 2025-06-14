# tests/test_mda_agent.py

import pytest
from unittest.mock import MagicMock, patch

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'multi_tool_agent')))

from mda_agent import get_cloud_run_metrics, get_cloud_run_logs, generate_health_report

@pytest.fixture
def mock_monitoring_client(mocker):
    """Mocks the google.cloud.monitoring_v3.MetricServiceClient."""
    mock_client_class = mocker.patch('mda_agent.monitoring_v3.MetricServiceClient')
    mock_client_instance = MagicMock()
    mock_client_class.return_value = mock_client_instance
    return mock_client_instance

@pytest.fixture
def mock_logging_client(mocker):
    """Mocks the google.cloud.logging_v2.Client."""
    mock_client_class = mocker.patch('mda_agent.logging_v2.Client')
    mock_client_instance = MagicMock()
    mock_client_class.return_value = mock_client_instance
    return mock_client_instance


def test_get_cloud_run_metrics_success(mock_monitoring_client):
    """Tests that get_cloud_run_metrics correctly processes successful API responses."""
    # --- Mock Setup ---
    # Simulate a response for the 'request_count' query
    mock_request_count_point = MagicMock()
    mock_request_count_point.value.int64_value = 150
    mock_request_count_result = MagicMock()
    mock_request_count_result.points = [mock_request_count_point]
    
    # Simulate responses for error counts (first 4xx, then 5xx)
    mock_4xx_point = MagicMock()
    mock_4xx_point.value.int64_value = 5
    mock_4xx_result = MagicMock()
    mock_4xx_result.points = [mock_4xx_point]
    
    mock_5xx_point = MagicMock()
    mock_5xx_point.value.int64_value = 2
    mock_5xx_result = MagicMock()
    mock_5xx_result.points = [mock_5xx_point]

    # Simulate responses for latency
    mock_p50_point = MagicMock()
    mock_p50_point.value.double_value = 75.5
    mock_p50_result = MagicMock()
    mock_p50_result.points = [mock_p50_point]
    
    mock_p95_point = MagicMock()
    mock_p95_point.value.double_value = 250.1
    mock_p95_result = MagicMock()
    mock_p95_result.points = [mock_p95_point]
    
    # Configure the list_time_series method to return different results based on the filter
    def list_time_series_side_effect(request):
        filter_str = request.get("filter", "")
        if "request_count" in filter_str and "response_code_class" not in filter_str:
            return [mock_request_count_result]
        elif 'response_code_class = "4xx"' in filter_str:
            return [mock_4xx_result]
        elif 'response_code_class = "5xx"' in filter_str:
            return [mock_5xx_result]
        elif "request_latencies" in filter_str and "ALIGN_PERCENTILE_50" in str(request.get("aggregation")):
            return [mock_p50_result]
        elif "request_latencies" in filter_str and "ALIGN_PERCENTILE_95" in str(request.get("aggregation")):
            return [mock_p95_result]
        return []
        
    mock_monitoring_client.list_time_series.side_effect = list_time_series_side_effect

    # --- Function Call ---
    result = get_cloud_run_metrics(
        project_id="p", service_id="s", location="l", time_window_minutes=10
    )

    # --- Assertions ---
    assert result["status"] == "SUCCESS"
    assert result["metrics"]["request_count"] == 150
    assert result["metrics"]["error_count"] == 7 # 5 + 2
    assert result["metrics"]["p50_latency_ms"] == 75.5
    assert result["metrics"]["p95_latency_ms"] == 250.1


def test_get_cloud_run_logs_success(mock_logging_client):
    """Tests that get_cloud_run_logs correctly processes a successful API response."""
    # --- Mock Setup ---
    mock_log_entry = MagicMock()
    mock_log_entry.timestamp.isoformat.return_value = "2025-06-12T10:00:00Z"
    mock_log_entry.severity = "ERROR"
    mock_log_entry.payload = "This is a test error log."
    
    mock_logging_client.list_entries.return_value = [mock_log_entry]

    # --- Function Call ---
    result = get_cloud_run_logs(
        project_id="p", service_id="s", location="l", max_entries=1
    )

    # --- Assertions ---
    assert result["status"] == "SUCCESS"
    assert len(result["log_entries"]) == 1
    assert result["log_entries"][0]["severity"] == "ERROR"
    assert "This is a test error log" in result["log_entries"][0]["text_payload"]


def test_generate_health_report():
    """Tests the string formatting of the generate_health_report function."""
    mock_metrics = {"status": "SUCCESS", "metrics": {"request_count": 100, "error_count": 5}, "time_window_minutes": 10}
    mock_logs = {"status": "SUCCESS", "log_entries": [{"timestamp": "T1", "severity": "ERROR", "text_payload": "Log message 1"}]}
    
    result = generate_health_report(
        service_id="test-svc",
        metrics_report=mock_metrics,
        logs_report=mock_logs
    )

    assert "Health Report Data for Service: test-svc" in result
    assert "Request Count: 100" in result
    assert "Error Count (4xx+5xx): 5" in result
    assert "[ERROR] Log message 1" in result
