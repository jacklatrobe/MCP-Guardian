"""FastAPI application factory with lifespan management."""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from .config import settings
from .db import init_db, AsyncSessionLocal
from .models import MCPService, MCPSnapshot, ApprovalStatus
from .routers import admin_api, admin_ui, proxy
from .scheduler.route_poller import poll_routes
from .scheduler.check_scheduler import check_scheduler
from .services.snapshotter import take_snapshot

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for startup and shutdown tasks.
    
    This starts background schedulers that run continuously:
    - Route poller: refreshes in-memory route registry from DB
    - Check scheduler: performs periodic capability checks
    """
    logger.info("Starting MCP Guardian...")
    
    # Log admin password (generated or from config)
    if settings.admin.password:
        logger.info("Admin password loaded from config.yml")
        logger.info(f"Admin password: '{settings.admin_password}' (length: {len(settings.admin_password)})")
    else:
        logger.warning(f"⚠️  No admin password in config.yml - Generated random password: {settings.admin_password}")
        logger.warning(f"⚠️  Save this password! It will be required to access the admin interface.")
    
    if settings.admin.disable_ui:
        logger.info("Admin UI and API are DISABLED (disable_ui=true in config)")
    
    # Initialize database
    await init_db()
    logger.info("Database initialized")
    
    # Upsert services from config.yml
    await upsert_services_from_config()
    
    # Start background tasks
    route_poller_task = asyncio.create_task(poll_routes())
    check_scheduler_task = asyncio.create_task(check_scheduler())
    
    logger.info("Background schedulers started")
    logger.info(f"MCP Guardian listening on {settings.host}:{settings.port}")
    
    yield
    
    # Shutdown: cancel background tasks
    logger.info("Shutting down MCP Guardian...")
    route_poller_task.cancel()
    check_scheduler_task.cancel()
    
    try:
        await route_poller_task
    except asyncio.CancelledError:
        pass
    
    try:
        await check_scheduler_task
    except asyncio.CancelledError:
        pass
    
    logger.info("MCP Guardian shut down complete")


async def upsert_services_from_config():
    """
    Upsert services from config.yml into the database.
    
    Only adds services that don't already exist (by name).
    """
    if not settings.services:
        logger.info("No services defined in config.yml")
        return
    
    async with AsyncSessionLocal() as db:
        for service_config in settings.services:
            # Check if service already exists
            result = await db.execute(
                select(MCPService).where(MCPService.name == service_config.name)
            )
            existing = result.scalar_one_or_none()
            
            if existing:
                logger.info(f"Service '{service_config.name}' already exists - skipping")
                continue
            
            # Take snapshot
            try:
                logger.info(f"Adding service from config: {service_config.name}")
                snapshot_result = await take_snapshot(service_config.upstream_url)
                
                # Create service
                db_service = MCPService(
                    name=service_config.name,
                    upstream_url=service_config.upstream_url,
                    enabled=service_config.enabled,
                    check_frequency_minutes=service_config.check_frequency_minutes,
                )
                db.add(db_service)
                await db.flush()
                
                # Create initial snapshot with user_approved status
                db_snapshot = MCPSnapshot(
                    service_id=db_service.id,
                    snapshot_json=snapshot_result.snapshot_json,
                    snapshot_hash=snapshot_result.snapshot_hash,
                    approved_status=ApprovalStatus.USER_APPROVED,
                )
                db.add(db_snapshot)
                
                await db.commit()
                logger.info(f"✓ Service '{service_config.name}' added from config (hash: {snapshot_result.snapshot_hash[:16]}...)")
                
            except Exception as e:
                logger.error(f"✗ Failed to add service '{service_config.name}' from config: {e}")
                await db.rollback()


# Create FastAPI app
app = FastAPI(
    title="MCP Guardian",
    description="FastAPI-based MCP proxy with capability validation and auto-disable",
    version="0.1.0",
    lifespan=lifespan,
)

# Add CORS middleware (POC - adjust for production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
app.mount("/static", StaticFiles(directory="mcp_guardian/app/static"), name="static")

# Conditionally include admin routers (can be disabled via config)
if not settings.admin.disable_ui:
    app.include_router(admin_ui.router)  # Admin UI
    app.include_router(admin_api.router)  # Admin API
    logger.info("Admin UI and API routes mounted")
else:
    logger.info("Admin UI and API routes DISABLED by configuration")

# Always include proxy (main functionality)
app.include_router(proxy.router)  # MCP proxy (wildcard)


@app.get("/")
async def root():
    """Root endpoint - redirect to admin UI."""
    return {
        "name": "MCP Guardian",
        "version": "0.1.0",
        "admin_ui": "/ADMIN/",
        "admin_api": "/api/admin/",
        "docs": "/docs"
    }


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "mcp_guardian.app.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )
