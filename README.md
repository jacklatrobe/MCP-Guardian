# MCP Guardian 🛡️

A **FastAPI-based MCP proxy** that lets you register multiple upstream MCP servers, expose each under a stable URL, periodically re-validate their capabilities, and **auto-disable** any server whose tools/prompts/resources/spec change until a human re-approves.

## Features

- ✅ **Proxy multiple MCP servers** under stable paths (`/{SERVICE_NAME}/mcp`)
- ✅ **Snapshot capabilities** on onboarding (tools, resources, prompts)
- ✅ **Periodic validation** with configurable check frequency
- ✅ **Auto-disable on changes** - services are automatically disabled if capabilities drift
- ✅ **Admin UI** for service management and diff viewing
- ✅ **RFC 8785 JCS** canonical JSON hashing for robust change detection
- ✅ **SSE streaming support** for real-time MCP interactions
- ✅ **SQLite storage** with JSON1 support

## Architecture

MCP Guardian sits between MCP clients and upstream MCP servers:

```
MCP Clients → MCP Guardian → Upstream MCP Servers
               (proxy + validator)
```

### Key Components

- **Proxy Layer**: Wildcard routing that forwards POST/GET/DELETE to upstream servers
- **Snapshotter**: Captures capabilities (tools/resources/prompts) via MCP protocol
- **Canonicalizer**: RFC 8785 JCS + SHA-256 hashing for deterministic fingerprints
- **Schedulers**: Background tasks for route polling and periodic checks
- **Admin UI**: Web interface for service management

## Quick Start

### Using Docker

```bash
# Build the image
docker build -t mcp-guardian .

# Run with auto-generated password (check logs for password)
docker run -d \
  -p 8000:8000 \
  --name mcp-guardian \
  mcp-guardian

# View logs to get the generated admin password
docker logs mcp-guardian

# Or run with custom config.yml
docker run -d \
  -p 8000:8000 \
  -v $(pwd)/config.yml:/app/config.yml:ro \
  -v mcp-guardian-data:/app/data \
  --name mcp-guardian \
  mcp-guardian
```

**Note**: If you mount a custom `config.yml` with a database path like `/app/data/mcp_guardian.db`, make sure to mount a volume to `/app/data` to persist your database.

### Using Python

```bash
# Install dependencies
pip install -e .

# Run the server (will generate random admin password)
python -m uvicorn mcp_guardian.app.main:app --host 0.0.0.0 --port 8000

# Or with custom config
cp config.yml.example config.yml
# Edit config.yml with your settings
python -m uvicorn mcp_guardian.app.main:app --host 0.0.0.0 --port 8000
```

## Configuration

MCP Guardian uses a `config.yml` file for all configuration. This file is **optional** - if not provided, sensible defaults will be used.

### Quick Start

1. **Copy the example config** (optional):
   ```bash
   cp config.yml.example config.yml
   ```

2. **Edit config.yml** to customize:
   - Admin password (random password generated if not set)
   - Database location
   - Polling intervals
   - Pre-configured MCP services

### Configuration File (`config.yml`)

```yaml
# Admin interface configuration
admin:
  password: "your-secure-password"  # Optional - random if not set
  disable_ui: false                  # Set true to disable admin UI/API

# Polling and scheduling
polling:
  interval_seconds: 60               # Scheduler wake-up frequency
  min_check_frequency: 5             # Minimum check frequency (minutes)

# Database
database:
  url: "sqlite+aiosqlite:///./mcp_guardian.db"

# Pre-configured services (optional)
services:
  - name: "my-service"
    upstream_url: "http://localhost:3000/mcp"
    enabled: true
    check_frequency_minutes: 15
```

### Security Notes

- **Admin Password**: If no password is set in `config.yml`, a random password is generated at startup and logged to the console. **Save this password!**
- **HTTP Basic Auth**: The admin interface uses HTTP Basic Authentication. Username can be anything; password must match the configured/generated password.
- **Disable Admin UI**: For production deployments managed entirely via `config.yml`, set `admin.disable_ui: true` to completely disable the admin interface.

### Deployment Scenarios

**Local Development**:
```bash
# No config file needed - defaults work fine
python -m uvicorn mcp_guardian.app.main:app --reload
# Watch logs for generated admin password
```

**Production (Docker with mounted config)**:
```bash
# Using a named volume for data persistence
docker run -d \
  -p 8000:8000 \
  -v /path/to/config.yml:/app/config.yml:ro \
  -v mcp-guardian-data:/app/data \
  --name mcp-guardian \
  mcp-guardian:latest

# Or using a bind mount for data
docker run -d \
  -p 8000:8000 \
  -v /path/to/config.yml:/app/config.yml:ro \
  -v /path/to/data:/app/data \
  --name mcp-guardian \
  mcp-guardian:latest
```

**Important**: If your `config.yml` specifies a database path like `/app/data/mcp_guardian.db`, ensure you mount a volume to `/app/data`. If using the default `./mcp_guardian.db`, the database will be created in `/app/` (the container's working directory).

### Using Docker Compose

Create a `docker-compose.yml` file:

```yaml
version: '3.8'

services:
  mcp-guardian:
    build: .
    ports:
      - "8000:8000"
    volumes:
      - ./config.yml:/app/config.yml:ro
      - mcp-data:/app/data
    restart: unless-stopped

volumes:
  mcp-data:
```

Then run:

```bash
docker-compose up -d
```

**GitOps Friendly**:
- Store `config.yml` in version control
- Services defined in config are auto-upserted to database on startup
- Existing services (by name) are never overwritten
- Perfect for CI/CD pipelines and infrastructure-as-code

## Usage

### Admin UI

Navigate to `http://localhost:8000/ADMIN/` to access the admin interface.

**Authentication**: You'll be prompted for HTTP Basic Auth credentials. Username can be anything; password must match the value in `config.yml` (or the generated password from logs).

#### Overview

The admin interface provides a dashboard to manage all your MCP services:

![MCP Guardian Admin UI - Service List](docs/admin-ui-1.png)

*Service list showing enabled services with their upstream URLs, check frequencies, and snapshot approval status*

#### Adding a Service

1. Click **"Add Service"**
2. Fill in:
   - **Service Name**: Alphanumeric identifier (e.g., `my-mcp-service`)
   - **Upstream MCP URL**: Full URL to upstream MCP endpoint (e.g., `http://localhost:3000/mcp`)
   - **Check Frequency**: Minutes between checks (0 = never, minimum 5)
   - **Enable**: Whether to enable the service immediately
3. Click **"Save"**

The system will:
- Initialize the upstream server
- List all tools, resources, and prompts
- Create a canonical JSON snapshot
- Mark it as `user_approved`
- Expose the service at `/{SERVICE_NAME}/mcp`

#### Viewing Service Details

Click **"View"** on any service to see:
- Service configuration
- Recent snapshots
- Diff between approved and latest snapshots
- Actions: Approve, Enable/Disable, Delete

![MCP Guardian Admin UI - Service Details](docs/admin-ui-2.png)

*Service detail view showing configuration, snapshot history, and approval status*

#### Handling Changes

When the periodic checker detects capability changes:
1. Service is **automatically disabled**
2. New snapshot is marked as `unapproved`
3. Admin reviews the diff in the UI
4. Admin clicks **"Approve Latest Snapshot"** to re-enable

## How It Works

### Initialization Flow

1. Admin creates a service via UI/API
2. Guardian sends `initialize` to upstream
3. Guardian calls `tools/list`, `resources/list`, `prompts/list`
4. Capabilities are sorted, canonicalized (RFC 8785), and hashed (SHA-256)
5. Snapshot stored with `user_approved` status
6. Service enabled and added to route registry

### Periodic Check Flow

Every minute (configurable):

1. Scheduler identifies services due for checks (based on `check_frequency_minutes`)
2. For each due service:
   - Take new snapshot
   - Compare hash with last approved hash
   - If **same**: Create snapshot with `system_approved` status
   - If **different**: Create snapshot with `unapproved` status and **disable service**
3. Route registry reloaded to reflect changes

### Proxy Flow

1. Client sends request to `/{service_name}/mcp`
2. Guardian checks route registry for enabled status
3. If disabled: Return `HTTP 403 Forbidden`. If not configured, it returns `HTTP 404`.
4. If enabled: Forward request to upstream, preserving:
   - Headers: `MCP-Protocol-Version`, `Mcp-Session-Id`, `Last-Event-ID`
   - Body: Raw JSON-RPC
   - SSE: Event stream with proper `id:` propagation
5. Stream response back to client

## Security Considerations (POC)

This is a **Proof of Concept** with basic security:

- ✅ Single shared admin token (env var)
- ✅ Token-based API authentication
- ❌ No HTTPS (use reverse proxy)
- ❌ No rate limiting
- ❌ No audit trail export
- ❌ No multi-tenant RBAC

## License

See [LICENSE.md](LICENSE.md)