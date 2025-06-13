# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container at /app
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# MODIFIED: Copy the *contents* of your multi_tool_agent directory
# into the container's /app directory.
COPY ./multi_tool_agent/ .

# Expose port 8080 to the outside world
EXPOSE 8080

# Command to run the API server when the container launches
# This remains the same, as main_api.py will now be at the root of /app
CMD ["uvicorn", "main_api:app", "--host", "0.0.0.0", "--port", "8080"]