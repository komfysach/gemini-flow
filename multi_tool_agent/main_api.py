# main_api.py

import logging
import asyncio
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import os
import uuid

# MODIFIED: Import the Runner, agent, session service, and genai types
try:
    from agent import agent as moa_agent
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types as genai_types
    logging.info("Successfully imported Master Orchestrator Agent and ADK components.")
except ImportError as e:
    logging.critical(f"Fatal: Could not import the main agent or ADK components. Error: {e}")
    moa_agent = None
    Runner = None
    InMemorySessionService = None
    genai_types = None

# Configure the FastAPI app
app = FastAPI()
logging.basicConfig(level=logging.INFO)

# --- MODIFIED: Global variables for the Runner and a fixed session ---
# For this web app, we will use a single, fixed session for all users
# to exactly match the documentation's pattern and resolve the "Session not found" error.
APP_NAME = "gemini-flow"
USER_ID = "webapp_user_01"
SESSION_ID = "shared_session_01"


@app.on_event("startup")
async def startup_event():
    """
    On application startup, initialize the ADK Runner and create the
    single, shared session that all web requests will use.
    """
    global runner
    if moa_agent and Runner and InMemorySessionService:
        session_service = InMemorySessionService()
        runner = Runner(
            agent=moa_agent,
            app_name=APP_NAME,
            session_service=session_service
        )
        try:
            # Create the session so it exists before any requests come in.
            await runner.session_service.create_session(
                app_name=APP_NAME,
                user_id=USER_ID,
                session_id=SESSION_ID
            )
            logging.info(f"Successfully created shared session: {SESSION_ID}")
        except Exception as e:
            logging.critical(f"Failed to create persistent session on startup: {e}")
            runner = None # Disable runner if session creation fails
    else:
        logging.critical("Runner could not be initialized due to import errors.")


# Construct an absolute path to the 'static' directory
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

class UserQuery(BaseModel):
    query: str

@app.post("/invoke")
async def invoke_agent(user_query: UserQuery):
    """
    This endpoint receives a user's query, uses the ADK Runner to process it
    within the pre-existing shared session, and returns the final response.
    """
    query = user_query.query
    if not runner or not genai_types:
        raise HTTPException(status_code=500, detail="Agent Runner is not available. Check startup logs.")
    if not query:
        raise HTTPException(status_code=400, detail="Query cannot be empty.")

    logging.info(f"Received query for Runner: '{query}' in session {SESSION_ID}")

    try:
        final_response_text = "Agent did not produce a final response."
        
        # Create a Content object as required by the 'new_message' parameter.
        user_content_message = genai_types.Content(role='user', parts=[genai_types.Part(text=query)])
        
        # MODIFIED: Call run_async and process events exactly as shown in the documentation.
        async for event in runner.run_async(
            new_message=user_content_message,
            session_id=SESSION_ID,
            user_id=USER_ID
        ):
            # Check for the final response event
            if event.is_final_response():
                if event.content and event.content.parts:
                    # Extract the text from the first part of the content
                    final_response_text = event.content.parts[0].text
                elif event.actions and event.actions.escalate:
                    final_response_text = f"Agent escalated: {event.error_message or 'No specific message.'}"
                break # Stop processing after finding the final response

        logging.info(f"Returning final processed response from Runner for session {SESSION_ID}.")
        return {"response": final_response_text}

    except Exception as e:
        logging.exception(f"An error occurred while running the agent with the ADK Runner.")
        raise HTTPException(status_code=500, detail=f"An internal server error occurred: {e}")

# Mount a static directory to serve the HTML file
if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/")
async def read_root():
    index_html_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_html_path):
        return FileResponse(index_html_path)
    else:
        raise HTTPException(status_code=404, detail="index.html not found.")