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

# Set environment variables for better logging in containers
ENV PYTHONUNBUFFERED=1
ENV PYTHONIOENCODING=utf-8
ENV LOG_LEVEL=INFO

# Expose port 8080 to the outside world
EXPOSE 8080

# Command to run the API server with proper logging configuration
CMD ["uvicorn", "main_api:app", "--host", "0.0.0.0", "--port", "8080", "--log-level", "info", "--access-log"]