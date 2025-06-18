# main_api.py

import logging
import asyncio
import json
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
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

# Initialize runner as None - will be set in startup_event
runner = None


@app.on_event("startup")
async def startup_event():
    """
    On application startup, initialize the ADK Runner and create the
    single, shared session that all web requests will use.
    """
    global runner
    
    logging.info("Starting up GeminiFlow application...")
    
    if moa_agent and Runner and InMemorySessionService:
        try:
            logging.info("Initializing ADK components...")
            session_service = InMemorySessionService()
            runner = Runner(
                agent=moa_agent,
                app_name=APP_NAME,
                session_service=session_service
            )
            logging.info("ADK Runner created successfully")
            
            # Create the session so it exists before any requests come in.
            await runner.session_service.create_session(
                app_name=APP_NAME,
                user_id=USER_ID,
                session_id=SESSION_ID
            )
            logging.info(f"Successfully created shared session: {SESSION_ID}")
            
        except Exception as e:
            logging.critical(f"Failed to initialize runner or create session: {e}")
            runner = None # Ensure runner is None if initialization fails
    else:
        logging.critical("Runner could not be initialized due to import errors.")
        logging.critical(f"moa_agent: {moa_agent is not None}")
        logging.critical(f"Runner: {Runner is not None}")
        logging.critical(f"InMemorySessionService: {InMemorySessionService is not None}")
        runner = None


# Construct an absolute path to the 'static' directory
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

class UserQuery(BaseModel):
    query: str

def create_sse_message(message_type: str, data: str) -> str:
    """Create a Server-Sent Event formatted message."""
    return f"data: {json.dumps({'type': message_type, 'data': data})}\n\n"

@app.post("/invoke")
async def invoke_agent(user_query: UserQuery):
    """
    This endpoint receives a user's query, uses the ADK Runner to process it
    within the pre-existing shared session, and returns the final response.
    """
    global runner
    
    query = user_query.query
    if not runner or not genai_types:
        error_msg = f"Agent Runner is not available. runner={runner is not None}, genai_types={genai_types is not None}"
        logging.error(error_msg)
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

@app.post("/invoke-stream")
async def invoke_agent_stream(user_query: UserQuery):
    """
    Streaming endpoint that provides real-time updates during agent processing.
    Returns Server-Sent Events (SSE) for progressive updates.
    """
    global runner
    
    query = user_query.query
    if not runner or not genai_types:
        error_msg = f"Agent Runner is not available. runner={runner is not None}, genai_types={genai_types is not None}"
        logging.error(error_msg)
        raise HTTPException(status_code=500, detail="Agent Runner is not available. Check startup logs.")
    if not query:
        raise HTTPException(status_code=400, detail="Query cannot be empty.")

    async def event_generator():
        try:
            # Send immediate acknowledgment
            yield create_sse_message("status", f"🚀 Processing your request: {query}")
            yield create_sse_message("status", "🔄 Initializing agent...")
            
            # Create a Content object as required by the 'new_message' parameter
            user_content_message = genai_types.Content(role='user', parts=[genai_types.Part(text=query)])
            
            # Track progress
            event_count = 0
            
            # Process events from the runner
            async for event in runner.run_async(
                new_message=user_content_message,
                session_id=SESSION_ID,
                user_id=USER_ID
            ):
                event_count += 1
                
                # Send progress updates
                if event_count == 1:
                    yield create_sse_message("status", "🎯 Agent is analyzing your request...")
                elif event_count == 2:
                    yield create_sse_message("status", "⚙️ Selecting appropriate tools...")
                elif event_count % 5 == 0:  # Every 5th event
                    yield create_sse_message("status", f"📊 Processing... ({event_count} steps completed)")
                
                # Check for tool calls or intermediate responses
                if hasattr(event, 'tool_calls') and event.tool_calls:
                    for tool_call in event.tool_calls:
                        tool_name = getattr(tool_call, 'name', 'unknown tool')
                        yield create_sse_message("status", f"🔧 Executing {tool_name}...")
                
                # Check for final response
                if event.is_final_response():
                    final_response_text = "Agent completed processing."
                    
                    if event.content and event.content.parts:
                        final_response_text = event.content.parts[0].text
                    elif event.actions and event.actions.escalate:
                        final_response_text = f"Agent escalated: {event.error_message or 'No specific message.'}"
                    
                    yield create_sse_message("status", "✅ Processing complete!")
                    yield create_sse_message("response", final_response_text)
                    yield create_sse_message("done", "")
                    break
                
                # Small delay to prevent overwhelming the client
                await asyncio.sleep(0.1)
            
            # If we exit the loop without a final response
            if event_count == 0:
                yield create_sse_message("status", "❌ No response received from agent")
                yield create_sse_message("response", "Sorry, I couldn't process your request.")
                yield create_sse_message("done", "")
            
        except Exception as e:
            logging.exception(f"Error in streaming endpoint: {e}")
            yield create_sse_message("error", f"An error occurred: {str(e)}")
            yield create_sse_message("done", "")

    return StreamingResponse(
        event_generator(),
        media_type="text/plain",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Content-Type": "text/event-stream",
        }
    )

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