# main_api.py

import logging
import asyncio
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import os

# NOTE: We do not import the agent directly, as we will run it as a subprocess.

# Configure the FastAPI app
app = FastAPI()
logging.basicConfig(level=logging.INFO)

# Construct an absolute path to the 'static' directory
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

class UserQuery(BaseModel):
    query: str

@app.post("/invoke")
async def invoke_agent(user_query: UserQuery):
    """
    This endpoint receives a user's query, starts the ADK CLI as a subprocess,
    sends the query to it, and returns the agent's response.
    """
    query = user_query.query
    if not query:
        raise HTTPException(status_code=400, detail="Query cannot be empty.")

    logging.info(f"Received query for ADK CLI: '{query}'")

    try:
        process = await asyncio.create_subprocess_exec(
            'adk', 'run', 'agent.agent',
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd='/app' # Ensure it runs in the correct directory inside the container
        )

        # Send the user's query to the agent's stdin and close the pipe.
        process.stdin.write(query.encode())
        await process.stdin.drain()
        process.stdin.close() # Closing stdin signals to the process that there is no more input.

        # Use asyncio.wait_for for a compatible timeout mechanism.
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=1200)

        # Decode the output
        response_text = stdout.decode().strip()
        error_text = stderr.decode().strip()

        # Log any errors from the subprocess
        if error_text:
            logging.error(f"ADK subprocess stderr: {error_text}")

        # Check if the process exited cleanly
        if process.returncode != 0:
            logging.error(f"ADK subprocess exited with code {process.returncode}")
            error_detail = error_text or f"ADK subprocess failed with exit code {process.returncode}."
            raise HTTPException(status_code=500, detail=error_detail)

        # Clean up the CLI output to find the final agent response
        last_response = ""
        for line in response_text.split('\n'):
            if not line.strip().startswith('[user]:'):
                if ']: ' in line:
                    last_response = line.split(']: ', 1)[1]
                else:
                    last_response = line
        
        logging.info(f"Returning final processed response: {last_response}")
        return {"response": last_response or "Agent processed the request but returned no text."}

    except asyncio.TimeoutError:
        logging.error("Agent invocation timed out.")
        raise HTTPException(status_code=504, detail="The agent workflow took too long to complete.")
    except Exception as e:
        logging.exception(f"An error occurred while running the ADK subprocess.")
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