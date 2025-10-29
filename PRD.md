# MCP Guardian — Technical PRD (v0.1, POC)

A **FastAPI-based MCP proxy** that lets you register multiple upstream MCP servers, expose each under a stable URL, periodically re-validate their capabilities, and **auto-disable** any server whose tools/prompts/resources/spec change until a human re-approves.

---

## 1) Problem statement

MCP servers can change out from under client configurations. We need a containerised service that:

* Proxies multiple upstream MCP servers under stable paths.
* Captures an authoritative **snapshot** of each server’s MCP surface (tools/resources/prompts, capabilities) at onboarding time.
* Re-checks on a schedule; **disables** a route if the upstream’s exposed surface deviates **in any way** from the last approved snapshot.
* Provides a minimal **/ADMIN/** UI to CRUD server configs and (re)approve changes.

The protocol details that matter (and will be proxied transparently) include **Streamable HTTP** (single MCP endpoint handling POST & GET with optional SSE), session handling, and initialization semantics. ([Model Context Protocol][1])

---

## 2) Goals & non-goals

### Goals (MVP/POC)

* **Proxy** MCP Streamable HTTP for many services under:

  * `http://mcp-guardian.whatever/{SERVICE_NAME}/mcp`
  * `http://mcp-guardian.whatever/ADMIN/` (UI + admin API)
* **Onboard** a service (name, upstream MCP URL, check frequency, enabled flag).
* **Snapshot** upstream server’s capabilities on onboarding:

  * `tools/list`, `resources/list`, `prompts/list` (+ optional read/get for completeness). ([Model Context Protocol][2])
* **Periodic checks** per service (min 5 min; 1 min granularity; weekly supported):

  * If snapshot **identical** → mark check `approved=system_approved`.
  * If **different** → mark `approved=false` and **auto-disable** the route.
* **Diff robustness**: use **canonical JSON** + hash (RFC 8785 JCS) to avoid false positives from ordering/whitespace. ([RFC Editor][3])
* **Session pass-through**: preserve Streamable HTTP semantics, including POST/GET, `text/event-stream` for streaming responses, version header, and re-delivery semantics. ([Model Context Protocol][1])
* **Single container** with **SQLite** storage (JSON1 enabled). ([SQLite][4])

### Non-goals (defer)

* AuthN/AuthZ for the Admin WebUI
* Horizontal scale & shared session stores.
* Multi-tenant RBAC; audit export integrations.
* Legacy HTTP+SSE transport back-compat (only if needed later). ([Model Context Protocol][1])

---

## 3) User stories

1. As an **admin**, I can add an MCP server at `/ADMIN/`, which triggers an **initialization** and **snapshot**, sets `approved=user_approved`, and (if enabled) exposes it at `/{SERVICE_NAME}/mcp`. ([Model Context Protocol][1])
2. As a **system**, I run **scheduled checks**; if the upstream’s surface diverges, I set `approved=false` and **disable** the route automatically.
3. As an **admin**, I can review diffs and re-enable a route, re-flagging the latest snapshot as `user_approved`.

---

## 4) Constraints & protocol references (key)

* **Streamable HTTP**: one endpoint supports POST (client→server JSON-RPC), optional SSE on POST responses, and GET for unsolicited SSE. Includes session and resumability guidance. ([Model Context Protocol][1])
* **Core methods** used to fingerprint server surface:

  * `tools/list`, `tools/call` (invocation not required for fingerprint), `notifications/tools/list_changed`. ([Model Context Protocol][2])
  * `resources/list`, `resources/read`, templates listing. ([Model Context Protocol][5])
  * `prompts/list`, `prompts/get`. ([Model Context Protocol][6])
* **JSON-RPC 2.0** message shape and error semantics. ([JSON-RPC][7])
* **FastAPI lifespan** for background schedulers (not `BackgroundTasks`, which are tied to request lifecycles). ([FastAPI][8])
* **SSE** server support via `sse-starlette`; upstream consumption via `httpx` + `httpx-sse`. ([GitHub][9])
* **SQLite JSON1** for JSON operations (bundled since 3.38.0). ([SQLite][4])
* **Canonical JSON hashing** via JCS. ([RFC Editor][3])

---

## 5) Functional requirements

### 5.1 Routing

* `/{SERVICE_NAME}/mcp` handles **POST**, **GET**, **DELETE** and **passes through**:

  * Body: raw JSON-RPC as-is.
  * Headers: `MCP-Protocol-Version`, `Accept: application/json, text/event-stream`, `Mcp-Session-Id`, `Last-Event-ID`, auth headers (if any) – all preserved. ([Model Context Protocol][1])
* Strong recommendation (POC): **one wildcard route** instead of dynamically adding/removing FastAPI routes at runtime. Enable/disable by **allow-list** in memory from DB—simpler, safer, avoids hot route surgery.

### 5.2 Initialization & snapshot

* On **create service**:

  1. POST `initialize` to upstream MCP endpoint (Streamable HTTP).
  2. If successful, immediately call:

     * `tools/list` (paginate until end),
     * `resources/list` (+ `resources/templates/list`),
     * `prompts/list`.
       Store **raw results** and a **normalized “fingerprint”**:
     * **Canonical JSON (JCS) string** → SHA-256 → `snapshot_hash`. ([Model Context Protocol][2])
  3. Persist snapshot row (`approved=user_approved`), set route `enabled` per admin selection.

### 5.3 Scheduled re-checks

* A **scheduler task** (lifespan-started) wakes every minute:

  * Reads services whose `check_frequency` divides current minute or are overdue.
  * For each **enabled** service: re-run the snapshot procedure; compare JCS hash:

    * **Same** → add row `approved=system_approved`; keep route enabled.
    * **Different** → add row `approved=false`; set `routes.enabled=false`.

### 5.4 Admin UI & API

* Minimal HTML (no SPA needed) to:

  * **List** services (name, URL, enabled, check freq, last status).
  * **Create/Update/Delete** service configs.
  * **View snapshots** (most recent approved vs latest check) and **diff** (JSON diff).
  * **Approve & re-enable** a changed service.
* Admin API endpoints documented below.

### 5.5 Proxy behaviour (sessions & SSE)

* **POST** passthrough: Forward body & headers to upstream and stream either JSON body or **SSE** back to client exactly as received (no mutation). ([Model Context Protocol][1])
* **GET** passthrough: Keep an upstream SSE connection per downstream client; forward events as they arrive; propagate `id:` for **resume** support via `Last-Event-ID`. ([Model Context Protocol][1])
* **Session ID mapping**: downstream `Mcp-Session-Id` is **passed through** to upstream (proxy should not mint its own), unless a future requirement demands session virtualization. Simpler & spec-aligned for POC. ([Model Context Protocol][1])

---

## 6) Non-functional requirements

* **Reliability**: tolerate upstream disconnects; on SSE disconnect, **reconnect** using `Last-Event-ID` if provided. (Client-side may also reconnect; proxy must not invent semantics.) ([Model Context Protocol][1])
* **Performance**: dozens of concurrent SSE streams; keep memory use modest.
* **Security (POC)**: single shared admin secret (env var); HTTPS termination external or by reverse proxy. Add **Origin** validation for any public deployment per MCP transport guidance. ([Model Context Protocol][1])
* **Observability**: structured logs, counters (routes enabled/disabled, check latency, SSE connections).

---

## 7) Data model (SQLite)

> Use SQLAlchemy 2.x ORM with SQLite (JSON1). For JSON columns, store raw payloads as text; transformations handled in code. ([SQLAlchemy Documentation][10])

**mcp_services**

* `id` (PK), `name` (unique), `upstream_url` (text),
* `enabled` (bool), `check_frequency_minutes` (int; 0 = no recheck; min 5),
* `created_at`, `updated_at`.

**mcp_snapshots**

* `id` (PK), `service_id` (FK),
* `snapshot_json` (text) – canonicalizable JSON of combined lists (tools/resources/prompts + optional metadata),
* `snapshot_hash` (char(64)),
* `approved_status` (enum: `user_approved`, `system_approved`, `unapproved`),
* `created_at`.

**audit_log** (optional POC)

* `id`, `ts`, `actor` (system|user), `action`, `details_json`.

> **Why a single combined snapshot?** Simpler “changed in any way” semantics; future versions can split per-domain if needed.

---

## 8) Fingerprint strategy

1. Compose a **deterministic** structure:

   * For each list (tools/resources/prompts), sort by a stable key (`name` / `uri`) and **remove fields that are known to fluctuate** (e.g., timestamps).
2. Canonicalize with **RFC 8785 JCS** (deterministic key ordering & formatting).
3. Hash with SHA-256 → `snapshot_hash`.
4. Compare current hash to last **approved** hash. If mismatch → disable route. ([RFC Editor][3])

> Rationale: avoids false positives from ordering/whitespace differences; matches cryptographic best practice. Libraries: `jcs` / `canonicaljson`. ([PyPI][11])

---

## 9) Admin API (POC)

```
POST   /api/admin/services
GET    /api/admin/services
GET    /api/admin/services/{name}
PATCH  /api/admin/services/{name}     # update URL, freq, enabled (admin-controlled)
DELETE /api/admin/services/{name}

POST   /api/admin/services/{name}/approve   # marks latest snapshot as user_approved, can re-enable
GET    /api/admin/services/{name}/snapshots # list recent snapshots + statuses
GET    /api/admin/services/{name}/diff      # returns JSON diff between last approved and latest
```

* Creating a service triggers `initialize` + full snapshot (see §5.2). ([Model Context Protocol][1])
* PATCH does **not** auto-approve; any change to upstream URL forces new snapshot.

---

## 10) Proxy endpoint semantics

`/{SERVICE_NAME}/mcp`

* **POST**: forward upstream; return **exact** upstream response (JSON body or `text/event-stream` stream). Preserve JSON-RPC 2.0 framing and error codes. ([Model Context Protocol][1])
* **GET**: open downstream SSE and forward upstream SSE (using `httpx` + `httpx-sse` client). ([PyPI][12])
* **DELETE**: forward as-is (used by some servers for explicit session termination). ([Model Context Protocol][1])
* **Disabled service**: respond `503 Service Unavailable` with body indicating route disabled pending review.

---

## 11) Scheduling & background execution

* Use **FastAPI lifespan** to start two long-running `asyncio.Task`s:

  * **Route poller** (runs every 60s): loads `mcp_services` and refreshes in-memory **allow-list**; no route surgery required thanks to wildcard path. ([FastAPI][8])
  * **Check scheduler** (runs every 60s): finds due services (enabled & overdue), executes snapshot, writes `mcp_snapshots`, flips `enabled=false` if changed.
* **Do not** rely on `BackgroundTasks` for these, as they are request-scoped helpers, not durable schedulers. ([FastAPI][13])

---

## 12) Security (POC stance)

* **Admin UI/API** behind a single shared bearer token or HTTP Basic; CSRF protection for form posts.
* Enforce **Origin** checks on MCP proxy endpoints when running on public hosts (recommended by MCP). ([Model Context Protocol][1])
* TLS termination via reverse proxy (Nginx/Caddy); container listens on localhost/cluster overlay.

---

## 13) Observability

* **Logs**: request ids, upstream latency, SSE open/close events, snapshot outcomes.
* **Metrics** (Prometheus ready):

  * `mcp_guardian_routes_enabled{service}` (gauge)
  * `mcp_guardian_snapshot_seconds` (histogram)
  * `mcp_guardian_sse_connections` (gauge)

---

## 14) Risks & mitigations

* **SSE bridging correctness** (resumes, multiple streams): adhere to spec; forward `id:` and respect `Last-Event-ID`. Prefer libraries with SSE helpers (`sse-starlette` for server, `httpx-sse` for client). ([Model Context Protocol][1])
* **Snapshot false positives**: use canonical JSON (RFC 8785); remove volatile fields; document exclusions. ([RFC Editor][3])
* **SQLite concurrency**: keep write operations short; run on a single container; revisit for Postgres later (JSONB/indexing differences). ([Stack Overflow][14])
* **Background jobs**: ensure they’re started via **lifespan** and stop cleanly on shutdown. ([FastAPI][8])

---

## 15) Technology choices (POC)

* **FastAPI** + **Starlette** (`lifespan` API). ([FastAPI][8])
* **httpx** (+ `httpx-sse`) for upstream calls & SSE consumption. ([PyPI][12])
* **sse-starlette** for downstream SSE responses. ([GitHub][9])
* **SQLAlchemy 2.x** ORM; **SQLite** (JSON1). ([SQLAlchemy Documentation][10])
* **Jinja2** templates; vanilla JS/Fetch for admin UI.
* **jcs** (RFC 8785) for canonicalization. ([PyPI][11])

---

## 16) File & module structure

```
mcp_guardian/
  app/
    main.py                    # FastAPI app factory + lifespan (starts schedulers)
    config.py                  # Settings (env vars: ADMIN_TOKEN, DB_URL, etc.)
    db.py                      # SQLAlchemy engine/session
    models.py                  # ORM models (services, snapshots, audit)
    schemas.py                 # Pydantic request/response models
    routers/
      admin_api.py             # /api/admin/... endpoints
      proxy.py                 # /{service_name}/mcp (GET/POST/DELETE)
      admin_ui.py              # /ADMIN/ (Jinja2 templates)
    services/
      route_registry.py        # In-memory allow-list, reloaded by poller
      snapshotter.py           # Initialize & list (tools/resources/prompts)
      canonicalize.py          # RFC 8785 JCS + exclusions + hashing
      proxy_client.py          # httpx/httpx-sse upstream interactions
      diff.py                  # JSON diff helpers (for UI)
    scheduler/
      route_poller.py          # every 60s: refresh allow-list from DB
      check_scheduler.py       # every 60s: determine due services & run checks
    static/
      admin/
        admin.css
        admin.js
    templates/
      admin/
        index.html
        service_form.html
        snapshots.html
  Dockerfile
  pyproject.toml
  README.md
```

**Rationale**

* `proxy.py` is a thin translation layer; all protocol nuance lives in `proxy_client.py`.
* `snapshotter.py` keeps MCP knowledge centralized (initialize + list flows).
* `canonicalize.py` isolates RFC 8785 logic for testability and later signing. ([RFC Editor][3])

---

## 17) Key flows (pseudocode)

### 17.1 Add service

```
POST /api/admin/services {name, upstream_url, enabled, check_freq}
 -> snapshot = snapshotter.take_snapshot(upstream_url)
 -> db.insert(service, enabled=..., check_freq=...)
 -> db.insert(snapshot, approved_status="user_approved")
 -> route_registry.reload()
```

### 17.2 Periodic check

```
for service in due_enabled_services():
    current = snapshotter.take_snapshot(service.upstream_url)
    if current.hash == last_approved_hash(service):
        db.insert(snapshot, approved_status="system_approved")
    else:
        db.insert(snapshot, approved_status="unapproved")
        db.update(service, enabled=False)
        route_registry.reload()
```

### 17.3 Proxy (POST)

```
assert route_registry.is_enabled(service_name)
resp = proxy_client.forward_post(service_name, request)
return stream_or_json(resp)  # mirror upstream: JSON or text/event-stream
```

---

## 18) API/Protocol specifics we *must* respect

* **Single MCP endpoint** per upstream; **POST** for client→server JSON-RPC; **GET** optional for unsolicited SSE; **DELETE** may be used for session termination. ([Model Context Protocol][1])
* For **requests leading to SSE**: downstream response `Content-Type: text/event-stream` with event framing preserved; forward upstream event `id:` so clients can use **Last-Event-ID** to resume. ([Model Context Protocol][1])
* **Initialization** precedes listing; capability negotiation is part of lifecycle. **We only need it during snapshotting**, not on hot path proxying. ([Model Context Protocol][15])
* **Tool/resource/prompt** listing method names and shapes per spec. ([Model Context Protocol][2])

---


## 21) Strong implementation opinions (why)

* **Wildcard proxy route** over dynamic route creation. Runtime surgery of FastAPI routes is fragile; a DB-backed allow-list is simpler and safer.
* **Lifespan tasks, not `BackgroundTasks`** for schedulers. The latter are request-scoped and unsuitable for durable, periodic work. ([FastAPI][8])
* **JCS canonicalization** over ad-hoc sorting to reduce false positives and future-proof for signatures. ([RFC Editor][3])
* **SSE libraries** on both sides to reduce correctness risk, especially for resume semantics. ([GitHub][9])

---

## 22) References

* MCP **Transports** (Streamable HTTP; sessions, SSE, version header). ([Model Context Protocol][1])
* MCP **Tools/Resources/Prompts** method names & schemas. ([Model Context Protocol][2])
* MCP **Architecture & lifecycle** overview. ([Model Context Protocol][17])
* **JSON-RPC 2.0** spec. ([JSON-RPC][7])
* **FastAPI lifespan** and background tasks caveat. ([FastAPI][8])
* **SSE** in Starlette/FastAPI and Python client. ([GitHub][9])
* **SQLite JSON1**. ([SQLite][4])
* **Canonical JSON (RFC 8785)** + Python libs. ([RFC Editor][3])

---

If you want, I can follow this PRD with a **scaffold** (FastAPI app factory + models + the snapshotter/proxy stubs) so you can run the POC in a single container immediately.

[1]: https://modelcontextprotocol.io/specification/2025-06-18/basic/transports "Transports - Model Context Protocol"
[2]: https://modelcontextprotocol.io/specification/2025-06-18/server/tools "Tools - Model Context Protocol"
[3]: https://www.rfc-editor.org/rfc/rfc8785?utm_source=chatgpt.com "RFC 8785: JSON Canonicalization Scheme (JCS)"
[4]: https://sqlite.org/json1.html?utm_source=chatgpt.com "JSON Functions And Operators - SQLite"
[5]: https://modelcontextprotocol.io/specification/2025-06-18/server/resources "Resources - Model Context Protocol"
[6]: https://modelcontextprotocol.io/specification/2025-06-18/server/prompts "Prompts - Model Context Protocol"
[7]: https://www.jsonrpc.org/specification?utm_source=chatgpt.com "JSON-RPC 2.0 Specification"
[8]: https://fastapi.tiangolo.com/advanced/events/?utm_source=chatgpt.com "Lifespan Events - FastAPI"
[9]: https://github.com/sysid/sse-starlette?utm_source=chatgpt.com "GitHub - sysid/sse-starlette"
[10]: https://docs.sqlalchemy.org/?utm_source=chatgpt.com "SQLAlchemy Documentation — SQLAlchemy 2.0 Documentation"
[11]: https://pypi.org/project/jcs/?utm_source=chatgpt.com "jcs · PyPI"
[12]: https://pypi.org/project/httpx-sse/?utm_source=chatgpt.com "httpx-sse · PyPI"
[13]: https://fastapi.tiangolo.com/tutorial/background-tasks/?utm_source=chatgpt.com "Background Tasks - FastAPI"
[14]: https://stackoverflow.com/questions/74187631/sqlalchemy-how-to-use-json-columns-with-indexes-interchangeably-between-sqlite-a?utm_source=chatgpt.com "python - SQLAlchemy How to use JSON columns with indexes ..."
[15]: https://modelcontextprotocol.io/specification/2025-03-26/basic/lifecycle?utm_source=chatgpt.com "Lifecycle - Model Context Protocol"
[16]: https://github.com/modelcontextprotocol/ruby-sdk/blob/main/examples/README.md?utm_source=chatgpt.com "ruby-sdk/examples/README.md at main - GitHub"
[17]: https://modelcontextprotocol.io/docs/learn/architecture?utm_source=chatgpt.com "Architecture overview - Model Context Protocol"
