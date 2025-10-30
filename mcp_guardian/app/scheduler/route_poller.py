"""Route poller - refreshes in-memory route registry from database."""
import asyncio
import logging

from sqlalchemy import select

from ..db import AsyncSessionLocal
from ..models import MCPService
from ..services.route_registry import route_registry
from ..config import settings

logger = logging.getLogger(__name__)


async def poll_routes():
    """
    Periodically poll database and refresh route registry.
    
    Runs every scheduler_interval_seconds (default 60s).
    """
    logger.info("Route poller started")
    
    while True:
        try:
            async with AsyncSessionLocal() as session:
                # Load all services
                result = await session.execute(select(MCPService))
                services = result.scalars().all()
                
                # Reload registry
                await route_registry.reload(services)
                
                logger.debug(f"Route registry refreshed: {len(services)} total services")
        
        except Exception as e:
            logger.error(f"Error in route poller: {e}", exc_info=True)
        
        # Sleep for configured interval
        await asyncio.sleep(settings.scheduler_interval_seconds)
