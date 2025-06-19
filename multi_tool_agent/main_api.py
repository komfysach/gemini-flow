# main_api.py

import logging
import asyncio
import json
import sys
import io
from contextlib import redirect_stdout
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
import os
import uuid

# Import the Runner, agent, session service, and genai types
try:
    from agent import root_agent as moa_agent # Ensure your main agent is named root_agent in agent.py
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

# Global variables for the Runner
runner: Runner = None
APP_NAME = "geminiflow"
USER_ID = "webapp_user_01"


@app.on_event("startup")
async def startup_event():
    """
    On application startup, initialize the ADK Runner.
    A new session will be created for each request.
    """
    global runner
    if moa_agent and Runner and InMemorySessionService:
        session_service = InMemorySessionService()
        runner = Runner(
            agent=moa_agent,
            app_name=APP_NAME,
            session_service=session_service
        )
        logging.info(f"Runner successfully initialized.")
    else:
        logging.critical("Runner could not be initialized due to import errors.")


# Construct an absolute path to the 'static' directory
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

class UserQuery(BaseModel):
    query: str

class PrintCapture:
    """Custom class to capture print statements and convert them to status updates"""
    def __init__(self, status_queue):
        self.status_queue = status_queue
        self.original_stdout = sys.stdout
        
    def write(self, text):
        # Send to original stdout for logging
        self.original_stdout.write(text)
        self.original_stdout.flush()
        
        # If it's a meaningful status message (contains emojis or specific keywords), send as status
        text = text.strip()
        if text and (
            any(emoji in text for emoji in ['🎯', '📦', '⚙️', '✅', '❌', '🚀', '🔍', '🔨', '🔐', '🏥', '💰', '📊', '📋', '🔄', '📁']) or
            any(keyword in text.lower() for keyword in ['starting', 'executing', 'completed', 'failed', 'step', 'processing'])
        ):
            try:
                self.status_queue.put_nowait(text)
            except:
                pass  # Ignore queue full errors
                
    def flush(self):
        self.original_stdout.flush()

async def stream_agent_response(query: str):
    """
    An async generator that runs the ADK agent and yields
    Server-Sent Events (SSE) for each interaction event and print statements.
    """
    if not runner or not genai_types:
        sse_data = {"type": "error", "data": "Agent Runner is not available."}
        yield f"data: {json.dumps(sse_data)}\n\n"
        return

    try:
        # Create a new session for this interaction
        session_id = str(uuid.uuid4())
        await runner.session_service.create_session(
            app_name=APP_NAME, user_id=USER_ID, session_id=session_id
        )
        logging.info(f"Created new session for request: {session_id}")
        
        # Send initial status
        yield f"data: {json.dumps({'type': 'status', 'data': f'🚀 Processing your request: {query}'})}\n\n"
        yield f"data: {json.dumps({'type': 'status', 'data': '🔄 Initializing agent...'})}\n\n"
        
        # Create a queue to capture print statements
        import queue
        status_queue = queue.Queue()
        print_capture = PrintCapture(status_queue)
        
        # Prepare the user's message in ADK format
        user_content_message = genai_types.Content(role='user', parts=[genai_types.Part(text=query)])
        
        # Redirect stdout to capture print statements
        original_stdout = sys.stdout
        sys.stdout = print_capture
        
        try:
            # Use runner.run_async to get a stream of events, as per documentation
            event_count = 0
            async for event in runner.run_async(
                new_message=user_content_message,
                session_id=session_id,
                user_id=USER_ID
            ):
                event_count += 1
                
                # Send periodic progress updates
                if event_count == 1:
                    yield f"data: {json.dumps({'type': 'status', 'data': '🎯 Agent is analyzing your request...'})}\n\n"
                elif event_count == 2:
                    yield f"data: {json.dumps({'type': 'status', 'data': '⚙️ Selecting appropriate tools...'})}\n\n"
                elif event_count % 5 == 0:
                    yield f"data: {json.dumps({'type': 'status', 'data': f'📊 Processing... ({event_count} steps completed)'})}\n\n"
                
                # Check for tool calls
                if hasattr(event, 'tool_calls') and event.tool_calls:
                    for tool_call in event.tool_calls:
                        tool_name = getattr(tool_call, 'name', 'unknown tool')
                        yield f"data: {json.dumps({'type': 'status', 'data': f'🔧 Executing {tool_name}...'})}\n\n"
                
                # Check for captured print statements
                while not status_queue.empty():
                    try:
                        status_text = status_queue.get_nowait()
                        yield f"data: {json.dumps({'type': 'status', 'data': status_text})}\n\n"
                    except queue.Empty:
                        break
                
                # Log the event for debugging
                if event:
                    logging.info(f"Received event: {event}")
                
                # Check for the final response using the documented method
                if event.is_final_response():
                    final_response_text = "Agent finished."  # Default if no text
                    if event.content and event.content.parts:
                        final_response_text = event.content.parts[0].text
                    
                    # Check for any remaining status messages
                    while not status_queue.empty():
                        try:
                            status_text = status_queue.get_nowait()
                            yield f"data: {json.dumps({'type': 'status', 'data': status_text})}\n\n"
                        except queue.Empty:
                            break
                    
                    yield f"data: {json.dumps({'type': 'status', 'data': '✅ Processing complete!'})}\n\n"
                    yield f"data: {json.dumps({'type': 'response', 'data': final_response_text})}\n\n"
                    break  # Stop after the final response
                
                # Small delay to allow print statements to be captured
                await asyncio.sleep(0.1)
        
        finally:
            # Restore original stdout
            sys.stdout = original_stdout

    except Exception as e:
        # Restore stdout in case of error
        sys.stdout = original_stdout
        logging.exception("Error during agent streaming invocation.")
        error_data = {"type": "error", "data": f"An internal server error occurred: {e}"}
        yield f"data: {json.dumps(error_data)}\n\n"
    finally:
        # Signal that the stream is done
        logging.info("Streaming response finished.")
        yield f"data: {json.dumps({'type': 'done'})}\n\n"


@app.post("/invoke-stream")
async def invoke_agent_stream(user_query: UserQuery):
    """
    Streaming endpoint that provides real-time feedback including captured print statements.
    """
    query = user_query.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query cannot be empty.")
    
    return StreamingResponse(
        stream_agent_response(query), 
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Content-Type": "text/event-stream",
        }
    )

@app.post("/invoke")
async def invoke_agent_regular(user_query: UserQuery):
    """
    Regular endpoint that returns final response only (for non-streaming mode).
    """
    query = user_query.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query cannot be empty.")
    
    if not runner or not genai_types:
        raise HTTPException(status_code=500, detail="Agent Runner is not available.")

    try:
        # Create a new session for this interaction
        session_id = str(uuid.uuid4())
        await runner.session_service.create_session(
            app_name=APP_NAME, user_id=USER_ID, session_id=session_id
        )
        
        # Prepare the user's message in ADK format
        user_content_message = genai_types.Content(role='user', parts=[genai_types.Part(text=query)])
        
        # Use runner.run_async to get the final response
        final_response_text = "Agent finished."
        async for event in runner.run_async(
            new_message=user_content_message,
            session_id=session_id,
            user_id=USER_ID
        ):
            if event.is_final_response():
                if event.content and event.content.parts:
                    final_response_text = event.content.parts[0].text
                break
        
        return {"response": final_response_text}
        
    except Exception as e:
        logging.exception("Error during agent invocation.")
        raise HTTPException(status_code=500, detail=f"An internal server error occurred: {e}")


@app.get("/")
async def read_root():
    """Serve the main UI page."""
    static_dir_path = os.path.join(os.path.dirname(__file__), "static")
    index_html_path = os.path.join(static_dir_path, "index.html")
    if os.path.exists(index_html_path):
        return FileResponse(index_html_path)
    else:
        raise HTTPException(status_code=404, detail="index.html not found.")

# Mount a static directory to serve the HTML file
static_dir_path = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(static_dir_path):
    app.mount("/static", StaticFiles(directory=static_dir_path), name="static")