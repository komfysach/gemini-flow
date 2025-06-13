# main_api.py

import logging
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

# Import your main agent instance from agent.py
# This assumes your MOA instance is named 'agent' in that file
try:
    from agent import agent as moa_agent
    logging.info("Successfully imported Master Orchestrator Agent.")
except ImportError as e:
    logging.critical(f"Fatal: Could not import the main agent. Error: {e}")
    moa_agent = None

# Configure the FastAPI app
app = FastAPI()
logging.basicConfig(level=logging.INFO)

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

# Mount a static directory to serve the HTML file
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def read_root():
    return FileResponse('static/index.html')
