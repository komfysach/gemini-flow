# main_api.py

import logging
import asyncio
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import os

# Import the Runner, agent, and the default session service
try:
    from agent import agent as moa_agent
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    logging.info("Successfully imported Master Orchestrator Agent and ADK components.")
except ImportError as e:
    logging.critical(f"Fatal: Could not import the main agent or ADK components. Error: {e}")
    moa_agent = None
    Runner = None
    InMemorySessionService = None

# Configure the FastAPI app
app = FastAPI()
logging.basicConfig(level=logging.INFO)

# Create a single runner instance for the application
if moa_agent and Runner and InMemorySessionService:
    runner = Runner(
        agent=moa_agent,
        app_name="geminiflow",
        session_service=InMemorySessionService()
    )
else:
    runner = None

# Construct an absolute path to the 'static' directory
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

class UserQuery(BaseModel):
    query: str

@app.post("/invoke")
async def invoke_agent(user_query: UserQuery):
    """
    This endpoint receives a user's query, uses the ADK Runner to process it,
    and returns the final response.
    """
    query = user_query.query
    if not runner:
        raise HTTPException(status_code=500, detail="Agent Runner is not available due to import errors.")
    if not query:
        raise HTTPException(status_code=400, detail="Query cannot be empty.")

    logging.info(f"Received query for Runner: '{query}'")

    try:
        final_response_text = ""
        async for event in runner.run_async(request={"text": query}):
            if event.type == "text" and event.data.get("text"):
                # Accumulate the response text from all text events
                final_response_text += event.data["text"]

        logging.info(f"Returning final processed response from Runner.")
        return {"response": final_response_text or "Agent processed the request but returned no text."}

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