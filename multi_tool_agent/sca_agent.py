# sca_agent.py
# Agent Development Kit (ADK) Source Control Agent (SCA) for GeminiFlow

import os
import logging
from google.adk.agents import Agent
from github import Github, UnknownObjectException
from dotenv import load_dotenv 
load_dotenv()

# Configure basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Configuration ---
GITHUB_TOKEN = os.getenv("GITHUB_PAT")

# Target repository details (these would typically be passed by the MOA)
DEFAULT_GITHUB_REPO_FULL_NAME = "komfysach/gemini-flow-hello-world" # REPLACE with your actual repo full name
DEFAULT_BRANCH = "main" # Or "master", or your target branch

# --- SCA Tools ---

def get_latest_commit_sha(
    repo_full_name: str,
    branch_name: str
) -> dict:
    """
    Fetches the latest commit SHA for a specified branch of a GitHub repository.

    Args:
        repo_full_name (str): The full name of the repository (e.g., "username/repo-name").
        branch_name (str): The name of the branch (e.g., "main", "master", "develop").

    Returns:
        dict: A dictionary containing the status, commit SHA if successful,
              and any error messages.
              Example success:
              {
                  "status": "SUCCESS",
                  "commit_sha": "a1b2c3d4e5f6...",
                  "message": "Successfully fetched latest commit SHA."
              }
              Example failure:
              {
                  "status": "FAILURE",
                  "error_message": "Could not find repository or branch."
              }
    """
    if not GITHUB_TOKEN:
        logging.error("GITHUB_PAT environment variable not set.")
        return {"status": "ERROR", "error_message": "GitHub Personal Access Token (GITHUB_PAT) not configured."}
    if not repo_full_name or not branch_name:
        return {"status": "ERROR", "error_message": "Repository full name and branch name are required."}

    logging.info(f"Attempting to get latest commit SHA for repo '{repo_full_name}', branch '{branch_name}'")

    try:
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(repo_full_name)
        branch = repo.get_branch(branch=branch_name)
        latest_commit_sha = branch.commit.sha
        
        logging.info(f"Successfully fetched commit SHA: {latest_commit_sha} for {repo_full_name}@{branch_name}")
        return {
            "status": "SUCCESS",
            "commit_sha": latest_commit_sha,
            "message": f"Successfully fetched latest commit SHA '{latest_commit_sha}' for {repo_full_name}@{branch_name}."
        }
    except UnknownObjectException:
        error_msg = f"Could not find repository '{repo_full_name}' or branch '{branch_name}'. Please check names and PAT permissions."
        logging.error(error_msg)
        return {"status": "FAILURE", "error_message": error_msg}
    except Exception as e:
        error_msg = f"An unexpected error occurred while fetching commit SHA: {str(e)}"
        logging.exception(error_msg) # Logs the full traceback
        return {"status": "ERROR", "error_message": error_msg}

# --- ADK Agent Definition ---
# This SCA agent is simple; its logic is primarily within its tools.
# It doesn't need its own LLM for decision-making for this specific task.
# The MOA would call its tools.

sca_agent = Agent(
    name="geminiflow_source_control_agent",
    description="An agent responsible for interacting with source control repositories like GitHub.",
    instruction=(
        "You are a Source Control Agent. You receive requests to fetch information from "
        "repositories, such as the latest commit SHA for a branch."
    ),
    tools=[get_latest_commit_sha],
    # No LLM model needed for this agent for this specific tool.
)

# --- Local Testing Example ---
if __name__ == "__main__":

    if not GITHUB_TOKEN:
        print("Error: GITHUB_PAT environment variable is not set. Please set it or add it to a .env file.")
    elif DEFAULT_GITHUB_REPO_FULL_NAME == "your_github_username/gemini-flow-hello-world":
        print(f"Error: Please update DEFAULT_GITHUB_REPO_FULL_NAME in the script with your actual GitHub repository (e.g., {os.getenv('USER', 'your_username')}/gemini-flow-hello-world).")
    else:
        print(f"--- Testing SCA: Fetching latest commit for {DEFAULT_GITHUB_REPO_FULL_NAME} on branch {DEFAULT_BRANCH} ---")
        
        report = get_latest_commit_sha(
            repo_full_name=DEFAULT_GITHUB_REPO_FULL_NAME,
            branch_name=DEFAULT_BRANCH
        )

        print("\n--- SCA Report ---")
        if report:
            for key, value in report.items():
                print(f"  {key}: {value}")
        else:
            print("  No report generated.")

        if report and report.get("status") == "SUCCESS":
            print("\nSCA Test: SUCCESS - Commit SHA fetched.")
        else:
            print("\nSCA Test: FAILED or ERRORED - Check messages above.")