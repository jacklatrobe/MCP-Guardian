#!/bin/sh
set -e

# Ensure data directory exists with correct permissions
mkdir -p /app/data
chmod 777 /app/data

# Test write access
echo "Testing write access to /app/data..."
touch /app/data/.test || echo "WARNING: Cannot write to /app/data"
rm -f /app/data/.test

# Execute the main command
exec "$@"
