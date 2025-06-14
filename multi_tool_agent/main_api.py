# main_api.py

import logging
import os # Import os for path manipulation
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

# Import your main agent instance from agent.py
try:
    from agent import agent as moa_agent
    logging.info("Successfully imported Master Orchestrator Agent.")
except ImportError as e:
    logging.critical(f"Fatal: Could not import the main agent. Error: {e}")
    moa_agent = None

# Configure the FastAPI app
app = FastAPI()
logging.basicConfig(level=logging.INFO)

# MODIFIED: Construct an absolute path to the 'static' directory
# This ensures that the path is correct whether run directly or via pytest.
# __file__ gives the path to the current script (main_api.py)
# os.path.dirname gets the directory of the script
# os.path.join combines it with 'static' to create a reliable path
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

if not os.path.isdir(STATIC_DIR):
    # This check helps during local development if the directory is missing
    logging.warning(f"Static directory not found at: {STATIC_DIR}. Root path will work, but static files may not.")
else:
     # Mount the static directory to serve the HTML, CSS, JS files
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class UserQuery(BaseModel):
    query: str

@app.post("/invoke")
async def invoke_agent(user_query: UserQuery):
    """
    This endpoint receives a user's query, passes it to the MOA,
    and returns the agent's response.
    """
    if not moa_agent:
        raise HTTPException(status_code=500, detail="Master Orchestrator Agent is not available due to import errors.")

    logging.info(f"Received query for MOA: '{user_query.query}'")
    try:
        # Use the invoke method that works for your ADK version
        response_data = moa_agent.invoke({"text": user_query.query})
        
        logging.info(f"MOA returned: {response_data}")

        # Extract the final text response to send back to the UI
        final_text = response_data.get("text", "")
        tool_output = response_data.get("tool_response", "")

        # Combine the LLM text and tool output for a comprehensive response
        if tool_output and isinstance(tool_output, str):
            if final_text:
                final_text += f"\n\n--- Workflow Execution Log ---\n{tool_output}"
            else:
                final_text = tool_output

        return {"response": final_text or "The agent processed the request but returned no text."}

    except Exception as e:
        logging.exception(f"An error occurred while invoking the agent.")
        raise HTTPException(status_code=500, detail=f"An internal error occurred: {e}")


@app.get("/")
async def read_root():
    # Use the absolute path for the FileResponse as well for robustness
    index_html_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_html_path):
        return FileResponse(index_html_path)
    else:
        raise HTTPException(status_code=404, detail="index.html not found.")
