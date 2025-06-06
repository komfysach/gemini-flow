# mda_agent.py
# Agent Development Kit (ADK) Monitoring & Diagnostics Agent (MDA) for GeminiFlow

import os
import logging
from datetime import datetime, timedelta, timezone
from google.adk.agents import LlmAgent
from google.cloud import monitoring_v3
from google.cloud import logging_v2 # For interacting with Cloud Logging API v2
from google.protobuf.json_format import MessageToDict
from google.protobuf.timestamp_pb2 import Timestamp
from dotenv import load_dotenv
load_dotenv()

# Configure basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- MDA Configuration ---
GCP_PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT")
DEFAULT_CLOUD_RUN_SERVICE_ID = os.getenv("TARGET_APP_CLOUD_RUN_SERVICE_NAME", "geminiflow-hello-world-svc")
DEFAULT_CLOUD_RUN_LOCATION = os.getenv("TARGET_APP_CLOUD_RUN_REGION", "us-central1")

# --- MDA Tools ---
def get_cloud_run_metrics(
    project_id: str,
    service_id: str,
    location: str,
    time_window_minutes: int = 15
) -> dict:
    """
    Fetches key metrics (request count, error count, latency) for a Cloud Run service
    over a specified time window.
    """
    if not all([project_id, service_id, location]):
        return {"status": "ERROR", "error_message": "Project ID, Service ID, and Location are required."}

    logging.info(f"MDA: Fetching metrics for Cloud Run service '{service_id}' in '{location}' for the last {time_window_minutes} minutes.")
    client = monitoring_v3.MetricServiceClient()
    project_name = f"projects/{project_id}"

    now_dt = datetime.now(timezone.utc)
    start_time_dt = now_dt - timedelta(minutes=time_window_minutes)

    start_time_proto = Timestamp()
    start_time_proto.FromDatetime(start_time_dt)
    end_time_proto = Timestamp()
    end_time_proto.FromDatetime(now_dt)

    interval = monitoring_v3.types.TimeInterval(
        start_time=start_time_proto,
        end_time=end_time_proto,
    )

    metrics_data = {
        "request_count": 0,
        "error_count": 0, 
        "p50_latency_ms": None,
        "p95_latency_ms": None,
    }
    
    common_filter_parts = [
        f'resource.type = "cloud_run_revision"',
        f'resource.labels.service_name = "{service_id}"',
        f'resource.labels.location = "{location}"'
    ]

    try:
        time_series_view_full = monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL

        # Request Count
        request_count_filter = ' AND '.join(common_filter_parts + ['metric.type = "run.googleapis.com/request_count"'])
        results = client.list_time_series(
            request={
                "name": project_name,
                "filter": request_count_filter,
                "interval": interval,
                "view": time_series_view_full,
                "aggregation": monitoring_v3.types.Aggregation(
                    alignment_period={"seconds": time_window_minutes * 60},
                    per_series_aligner=monitoring_v3.types.Aggregation.Aligner.ALIGN_SUM,
                    cross_series_reducer=monitoring_v3.types.Aggregation.Reducer.REDUCE_SUM,
                ),
            }
        )
        for result in results:
            for point in result.points:
                metrics_data["request_count"] += point.value.int64_value
        logging.info(f"MDA: Request count: {metrics_data['request_count']}")

        # Error Count
        for code_class in ["4xx", "5xx"]:
            error_filter = ' AND '.join(common_filter_parts + [
                'metric.type = "run.googleapis.com/request_count"',
                f'metric.labels.response_code_class = "{code_class}"'
            ])
            results = client.list_time_series(
                request={
                    "name": project_name,
                    "filter": error_filter,
                    "interval": interval,
                    "view": time_series_view_full,
                    "aggregation": monitoring_v3.types.Aggregation(
                        alignment_period={"seconds": time_window_minutes * 60},
                        per_series_aligner=monitoring_v3.types.Aggregation.Aligner.ALIGN_SUM,
                        cross_series_reducer=monitoring_v3.types.Aggregation.Reducer.REDUCE_SUM,
                    ),
                }
            )
            for result in results:
                for point in result.points:
                    metrics_data["error_count"] += point.value.int64_value
        logging.info(f"MDA: Error count (4xx+5xx): {metrics_data['error_count']}")

        # Latency
        latency_filter = ' AND '.join(common_filter_parts + ['metric.type = "run.googleapis.com/request_latencies"'])
        results = client.list_time_series(
            request={
                "name": project_name,
                "filter": latency_filter,
                "interval": interval,
                "view": time_series_view_full,
            }
        )
        for result in results: 
            if result.points:
                latest_point = result.points[0]
                if latest_point.value.distribution_value:
                    dist_value = latest_point.value.distribution_value
                    if dist_value.mean and dist_value.count > 0:
                         metrics_data["p50_latency_ms"] = round(dist_value.mean, 1)
                         metrics_data["p95_latency_ms"] = round(dist_value.mean * 2, 1) 
                         logging.info(f"MDA: Latency (mean as proxy for p50): {metrics_data['p50_latency_ms']} ms")
                break 

        return {
            "status": "SUCCESS",
            "metrics": metrics_data,
            "time_window_minutes": time_window_minutes,
            "message": "Metrics fetched successfully."
        }
    except Exception as e:
        error_msg = f"MDA: Error fetching metrics: {str(e)}"
        logging.exception(error_msg)
        return {"status": "ERROR", "error_message": error_msg, "metrics": metrics_data}


def get_cloud_run_logs(
    project_id: str,
    service_id: str,
    location: str, 
    time_window_minutes: int = 15,
    max_entries: int = 10
) -> dict:
    """
    Fetches recent logs for a Cloud Run service.
    """
    if not all([project_id, service_id, location]):
        return {"status": "ERROR", "error_message": "Project ID, Service ID, and Location are required."}

    logging.info(f"MDA: Fetching last {time_window_minutes} mins of logs for Cloud Run service '{service_id}' in '{location}', max {max_entries} entries.")
    
    client = logging_v2.Client(project=project_id)
    
    now = datetime.now(timezone.utc)
    start_time_dt = now - timedelta(minutes=time_window_minutes)
    
    # MODIFIED: Ensure RFC3339 UTC "Zulu" format precisely (YYYY-MM-DDTHH:MM:SS.ffffffZ)
    # .isoformat() produces up to microsecond precision if available.
    # We explicitly format to ensure it ends with 'Z' and has common precision.
    start_time_str = start_time_dt.strftime('%Y-%m-%dT%H:%M:%S.%fZ')


    log_filter = (
        f'resource.type="cloud_run_revision" '
        f'resource.labels.service_name="{service_id}" '
        f'resource.labels.location="{location}" '
        f'timestamp>="{start_time_str}"'
    )
    logging.info(f"MDA: Using log filter: {log_filter}") # Log the filter for debugging

    entries_data = []
    try:
        iterator = client.list_entries(
            filter_=log_filter,
            order_by=logging_v2.DESCENDING, 
            page_size=max_entries 
        )
        
        count = 0
        for entry in iterator:
            if count >= max_entries:
                break
            
            entry_timestamp_dt = entry.timestamp
            if isinstance(entry.timestamp, str): 
                 entry_timestamp_dt = datetime.fromisoformat(entry.timestamp.replace("Z", "+00:00"))
            elif entry.timestamp is None: 
                entry_timestamp_dt = datetime.now(timezone.utc)

            entry_dict = {
                "timestamp": entry_timestamp_dt.isoformat(),
                "severity": entry.severity if entry.severity else "DEFAULT",
            }

            if entry.payload is not None:
                if isinstance(entry.payload, str):
                    entry_dict["text_payload"] = entry.payload
                elif isinstance(entry.payload, dict): 
                    entry_dict["json_payload"] = entry.payload
            entries_data.append(entry_dict)
            count += 1
        
        logging.info(f"MDA: Fetched {len(entries_data)} log entries.")
        return {
            "status": "SUCCESS",
            "log_entries": entries_data,
            "message": f"Fetched {len(entries_data)} log entries."
        }
    except Exception as e:
        error_msg = f"MDA: Error fetching logs: {str(e)}"
        logging.exception(error_msg) # Log the full traceback
        return {"status": "ERROR", "error_message": error_msg, "log_entries": []}


def generate_health_report(
    service_id: str,
    metrics_report: dict, 
    logs_report: dict     
) -> str:
    """
    Formats metrics and logs into a string for LLM summarization.
    """
    logging.info(f"MDA: Generating health report data for service '{service_id}'.")
    report_parts = [f"Health Report Data for Service: {service_id}\n"]

    if metrics_report.get("status") == "SUCCESS":
        metrics = metrics_report.get("metrics", {})
        report_parts.append("Metrics:")
        report_parts.append(f"  - Time Window: {metrics_report.get('time_window_minutes')} minutes")
        report_parts.append(f"  - Request Count: {metrics.get('request_count', 'N/A')}")
        report_parts.append(f"  - Error Count (4xx+5xx): {metrics.get('error_count', 'N/A')}")
        report_parts.append(f"  - P50 Latency (ms, mean proxy): {metrics.get('p50_latency_ms', 'N/A')}")
        report_parts.append(f"  - P95 Latency (ms, rough proxy): {metrics.get('p95_latency_ms', 'N/A')}")
    else:
        report_parts.append(f"Metrics: Error - {metrics_report.get('error_message', 'Could not fetch metrics.')}")

    if logs_report.get("status") == "SUCCESS":
        log_entries = logs_report.get("log_entries", [])
        report_parts.append("\nRecent Logs:")
        if log_entries:
            for entry in log_entries:
                payload_str = "N/A"
                if "text_payload" in entry:
                    payload_str = entry["text_payload"]
                elif "json_payload" in entry:
                    payload_str = str(entry["json_payload"])
                
                report_parts.append(f"  - [{entry.get('timestamp')}] [{entry.get('severity')}] {payload_str[:150]}")
        else:
            report_parts.append("  - No recent log entries found.")
    else:
        report_parts.append(f"\nLogs: Error - {logs_report.get('error_message', 'Could not fetch logs.')}")
    
    return "\n".join(report_parts)


# --- ADK Agent Definition for MDA ---
mda_agent = LlmAgent(
    name="geminiflow_monitoring_diagnostics_agent",
    model="gemini-1.5-flash-latest", 
    description=(
        "The Monitoring & Diagnostics Agent for GeminiFlow. "
        "It fetches metrics and logs for deployed services and can generate health summaries."
    ),
    instruction=(
        "You are a Monitoring and Diagnostics Agent. Your role is to provide health reports for services. "
        "When asked for a health report for a service (e.g., 'geminiflow-hello-world-svc'), "
        "you should first use the 'get_cloud_run_metrics' tool to get performance metrics, "
        "then use the 'get_cloud_run_logs' tool to get recent log entries. "
        "After gathering this data, use the 'generate_health_report' tool to compile the raw data. "
        "Finally, based on the output of 'generate_health_report' (which is a formatted string of data), "
        "provide a concise, human-readable summary of the service's health. "
        "Highlight any significant errors, high error rates, or performance issues. "
        "If metrics or logs couldn't be fetched, mention that in your summary."
        "Example user query: 'What is the health of geminiflow-hello-world-svc in us-central1?'"
        "You would then call get_cloud_run_metrics with service_id='geminiflow-hello-world-svc', location='us-central1'. "
        "Then call get_cloud_run_logs with the same parameters. "
        "Then call generate_health_report with the outputs of the previous two tools. "
        "Then summarize the string output of generate_health_report."
    ),
    tools=[
        get_cloud_run_metrics,
        get_cloud_run_logs,
        generate_health_report
    ]
)

# --- Local Testing Example for MDA ---
if __name__ == "__main__":
    # ... (implementation of this local testing block remains the same) ...
    if not GCP_PROJECT_ID:
        print("MDA Test Error: GOOGLE_CLOUD_PROJECT environment variable is not set.")
    elif os.getenv("GOOGLE_CLOUD_LOCATION") is None: 
        print("MDA Test Error: GOOGLE_CLOUD_LOCATION environment variable for Vertex AI is not set.")
    else:
        print(f"--- Testing MDA: Generating health report for {DEFAULT_CLOUD_RUN_SERVICE_ID} ---")
        
        print("\nStep 1: Fetching metrics...")
        metrics_data = get_cloud_run_metrics(
            project_id=GCP_PROJECT_ID,
            service_id=DEFAULT_CLOUD_RUN_SERVICE_ID,
            location=DEFAULT_CLOUD_RUN_LOCATION,
            time_window_minutes=5 
        )
        print(f"Metrics Data: {metrics_data}")

        print("\nStep 2: Fetching logs...")
        logs_data = get_cloud_run_logs(
            project_id=GCP_PROJECT_ID,
            service_id=DEFAULT_CLOUD_RUN_SERVICE_ID,
            location=DEFAULT_CLOUD_RUN_LOCATION,
            time_window_minutes=5, 
            max_entries=5
        )
        print(f"Logs Data: {logs_data}")

        print("\nStep 3: Generating raw report data (input for LLM summarization)...")
        raw_report_string = generate_health_report(
            service_id=DEFAULT_CLOUD_RUN_SERVICE_ID,
            metrics_report=metrics_data,
            logs_report=logs_data
        )
        print("--- Raw Report Data ---")
        print(raw_report_string)
        print("-----------------------")

        print("\nStep 4: Simulating LLM summarization using mda_agent.invoke (requires ADK CLI for full test)")
        print("To test the LLM's summarization, run this agent via 'adk run .' and ask:")
        print(f"User: What is the health of {DEFAULT_CLOUD_RUN_SERVICE_ID} in {DEFAULT_CLOUD_RUN_LOCATION}?")

