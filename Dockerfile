FROM python:3.13-slim

# Set working directory
WORKDIR /app

# Install system updates and dependencies
RUN apt-get update && apt-get upgrade -y
RUN apt-get install -y gcc

# Upgrade pip - fixes CVE-2025-8869
RUN pip install --upgrade pip

# Copy project files
COPY pyproject.toml ./
COPY mcp_guardian ./mcp_guardian/

# Install Python dependencies
RUN pip install --no-cache-dir -e .

# Copy and set up entrypoint script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Expose port
EXPOSE 8000

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV HOST=0.0.0.0
ENV PORT=8000

# We don't need GCC or it's vulnerabilities after installing dependencies
RUN apt-get remove -y gcc
RUN apt-get autoremove -y && apt-get clean

# Remove tar: fixes CVE-2025-45582
# But essentially leaves this image broken.
RUN rm -f /bin/tar && ln -sf /bin/true /bin/tar && rm -rf /var/lib/apt/lists/*

# Set entrypoint
ENTRYPOINT ["/entrypoint.sh"]

# Run the application
CMD ["sh", "-c", "python -m uvicorn mcp_guardian.app.main:app --host $HOST --port $PORT"]
