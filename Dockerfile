FROM python:3.13-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml ./
COPY mcp_guardian ./mcp_guardian/

# Install Python dependencies
RUN pip install --no-cache-dir -e .

# Create directory for database persistence
RUN mkdir -p /app/data

# Expose port
EXPOSE 8000

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV HOST=0.0.0.0
ENV PORT=8000

# Run the application
CMD ["sh", "-c", "python -m uvicorn mcp_guardian.app.main:app --host $HOST --port $PORT"]
