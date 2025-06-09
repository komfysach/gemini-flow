# finops_agent.py
# Agent Development Kit (ADK) FinOps Agent for GeminiFlow

import os
import logging
from datetime import datetime, timedelta, timezone
from google.adk.agents import Agent # Or LlmAgent if you add Gemini summarization
from google.cloud import bigquery
from dotenv import load_dotenv
load_dotenv()

# Configure basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- FinOps Agent Configuration ---
# For local testing, ensure GOOGLE_APPLICATION_CREDENTIALS is set to the path of
# the geminiflow-finops-sa@... service account key file.
# This SA needs "BigQuery User" and "BigQuery Data Viewer" roles.
GCP_PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT")
# IMPORTANT: You MUST set this environment variable to the full ID of your BigQuery billing export table.
# e.g., "your-billing-project.your_billing_dataset.gcp_billing_export_v1_XXXXXX_XXXXXX_XXXXXX"
BIGQUERY_BILLING_TABLE = os.getenv("BIGQUERY_BILLING_TABLE", "your-project.your_dataset.gcp_billing_export_v1_XXXX") # REPLACE

# --- FinOps Agent Tools ---

def get_total_project_cost(days_ago: int = 7) -> dict:
    """
    Queries BigQuery to calculate the total cost for the current GCP project over a specified number of past days.

    Args:
        days_ago (int): The number of days to look back for cost data. Defaults to 7.

    Returns:
        dict: A dictionary containing the status, total cost, and time window.
    """
    if BIGQUERY_BILLING_TABLE == "your-project.your_dataset.gcp_billing_export_v1_XXXX":
        return {"status": "ERROR", "error_message": "BIGQUERY_BILLING_TABLE environment variable not set."}
    if not GCP_PROJECT_ID:
        return {"status": "ERROR", "error_message": "GCP_PROJECT_ID environment variable not set."}

    logging.info(f"FinOps: Calculating total cost for project '{GCP_PROJECT_ID}' for the last {days_ago} days.")
    client = bigquery.Client(project=GCP_PROJECT_ID)

    # Calculate the start date for the query
    start_date = (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime('%Y-%m-%d')

    query = f"""
        SELECT
          SUM(cost) AS total_cost
        FROM
          `{BIGQUERY_BILLING_TABLE}`
        WHERE
          project.id = @project_id
          AND usage_start_time >= @start_date
    """
    
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("project_id", "STRING", GCP_PROJECT_ID),
            bigquery.ScalarQueryParameter("start_date", "STRING", start_date),
        ]
    )

    try:
        query_job = client.query(query, job_config=job_config)
        results = query_job.result() # Waits for the job to complete

        total_cost = 0
        for row in results:
            total_cost = row.total_cost if row.total_cost else 0
        
        message = f"Total cost for project '{GCP_PROJECT_ID}' over the last {days_ago} days is approximately ${total_cost:.2f}."
        logging.info(f"FinOps: {message}")
        return {
            "status": "SUCCESS",
            "total_cost": f"${total_cost:.2f}",
            "days_ago": days_ago,
            "message": message
        }
    except Exception as e:
        error_msg = f"FinOps: BigQuery query failed for total project cost: {e}"
        logging.exception(error_msg)
        return {"status": "ERROR", "error_message": error_msg}


def get_cost_by_service(days_ago: int = 7, limit: int = 5) -> dict:
    """
    Queries BigQuery for the top N most expensive services for the current GCP project
    over a specified number of past days.

    Args:
        days_ago (int): The number of days to look back for cost data. Defaults to 7.
        limit (int): The number of top services to return. Defaults to 5.

    Returns:
        dict: A dictionary containing the status and a list of services with their costs.
    """
    if BIGQUERY_BILLING_TABLE == "your-project.your_dataset.gcp_billing_export_v1_XXXX":
        return {"status": "ERROR", "error_message": "BIGQUERY_BILLING_TABLE environment variable not set."}
    if not GCP_PROJECT_ID:
        return {"status": "ERROR", "error_message": "GCP_PROJECT_ID environment variable not set."}

    logging.info(f"FinOps: Getting top {limit} services by cost for project '{GCP_PROJECT_ID}' for the last {days_ago} days.")
    client = bigquery.Client(project=GCP_PROJECT_ID)
    start_date = (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime('%Y-%m-%d')

    query = f"""
        SELECT
          service.description AS service_name,
          SUM(cost) AS total_cost
        FROM
          `{BIGQUERY_BILLING_TABLE}`
        WHERE
          project.id = @project_id
          AND usage_start_time >= @start_date
        GROUP BY
          service_name
        ORDER BY
          total_cost DESC
        LIMIT @limit
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("project_id", "STRING", GCP_PROJECT_ID),
            bigquery.ScalarQueryParameter("start_date", "STRING", start_date),
            bigquery.ScalarQueryParameter("limit", "INT64", limit),
        ]
    )

    try:
        query_job = client.query(query, job_config=job_config)
        results = query_job.result()

        cost_breakdown = []
        for row in results:
            cost_breakdown.append({
                "service_name": row.service_name,
                "total_cost": f"${row.total_cost:.2f}"
            })
        
        logging.info(f"FinOps: Successfully fetched cost breakdown by service.")
        return {
            "status": "SUCCESS",
            "cost_breakdown": cost_breakdown,
            "message": f"Successfully fetched cost breakdown for the top {limit} services."
        }
    except Exception as e:
        error_msg = f"FinOps: BigQuery query failed for cost by service: {e}"
        logging.exception(error_msg)
        return {"status": "ERROR", "error_message": error_msg}


# --- ADK Agent Definition ---
# For now, this is a simple Agent. If you add Gemini summarization to the tools,
# it should be converted to an LlmAgent.
finops_agent = Agent(
    name="geminiflow_finops_agent",
    description="An agent that provides financial operations (FinOps) insights by querying billing data from BigQuery.",
    instruction="You are a FinOps Agent. You answer questions about project costs by querying billing data.",
    tools=[
        get_total_project_cost,
        get_cost_by_service,
    ],
)

# --- Local Testing Example ---
if __name__ == "__main__":
    # Before running:
    # 1. Install the BigQuery client library: `pip install google-cloud-bigquery python-dotenv`
    # 2. Set the GOOGLE_APPLICATION_CREDENTIALS environment variable to the path of your
    #    geminiflow-finops-sa@... service account JSON key file.
    # 3. Set the GOOGLE_CLOUD_PROJECT environment variable to your GCP Project ID.
    # 4. CRITICAL: Set the BIGQUERY_BILLING_TABLE environment variable to your full BigQuery table ID.
    #    Find this in BigQuery console. e.g., "my-project-123.billing_data.gcp_billing_export_v1_..."
    
    if BIGQUERY_BILLING_TABLE == "your-project.your_dataset.gcp_billing_export_v1_XXXX":
        print("Error: Please set the BIGQUERY_BILLING_TABLE environment variable with your actual BigQuery billing export table ID.")
    else:
        print("--- Testing FinOps Agent Tools ---")
        
        print("\n--- Testing get_total_project_cost (last 30 days) ---")
        total_cost_report = get_total_project_cost(days_ago=30)
        import json
        print(json.dumps(total_cost_report, indent=2))
        
        print("\n--- Testing get_cost_by_service (last 30 days) ---")
        cost_by_service_report = get_cost_by_service(days_ago=30)
        print(json.dumps(cost_by_service_report, indent=2))

