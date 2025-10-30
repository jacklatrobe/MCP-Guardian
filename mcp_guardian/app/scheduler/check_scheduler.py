"""Check scheduler - performs periodic capability checks on enabled services."""
import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import select, desc

from ..db import AsyncSessionLocal
from ..models import MCPService, MCPSnapshot, ApprovalStatus
from ..services.snapshotter import take_snapshot
from ..services.route_registry import route_registry
from ..config import settings

logger = logging.getLogger(__name__)


async def is_check_due(service: MCPService, last_check_time: datetime | None) -> bool:
    """
    Determine if a service is due for a capability check.
    
    Args:
        service: MCPService object
        last_check_time: Timestamp of last check, or None
    
    Returns:
        True if check is due
    """
    # If check_frequency is 0, never check
    if service.check_frequency_minutes == 0:
        return False
    
    # If never checked, it's due
    if last_check_time is None:
        return True
    
    # Check if enough time has passed
    time_since_last_check = datetime.utcnow() - last_check_time
    check_interval = timedelta(minutes=service.check_frequency_minutes)
    
    return time_since_last_check >= check_interval


async def check_service(service: MCPService, session) -> bool:
    """
    Check a single service and update snapshot.
    
    Args:
        service: MCPService to check
        session: Database session
    
    Returns:
        True if service enabled status changed, False otherwise
    """
    logger.info(f"Checking service: {service.name}")
    
    try:
        # Track original enabled state
        original_enabled = service.enabled
        
        # Take new snapshot
        snapshot_result = await take_snapshot(service.upstream_url)
        
        # Get last approved snapshot hash
        approved_result = await session.execute(
            select(MCPSnapshot)
            .where(
                MCPSnapshot.service_id == service.id,
                MCPSnapshot.approved_status.in_([
                    ApprovalStatus.USER_APPROVED,
                    ApprovalStatus.SYSTEM_APPROVED
                ])
            )
            .order_by(desc(MCPSnapshot.created_at))
            .limit(1)
        )
        last_approved = approved_result.scalar_one_or_none()
        
        if not last_approved:
            logger.warning(f"No approved snapshot for {service.name}, marking as unapproved")
            approved_status = ApprovalStatus.UNAPPROVED
            service.enabled = False
        elif snapshot_result.snapshot_hash == last_approved.snapshot_hash:
            # No change - mark as system approved
            logger.info(f"Service {service.name} unchanged: {snapshot_result.snapshot_hash}")
            approved_status = ApprovalStatus.SYSTEM_APPROVED
        else:
            # Changed - mark as unapproved and disable
            logger.warning(
                f"Service {service.name} changed! "
                f"Old: {last_approved.snapshot_hash}, New: {snapshot_result.snapshot_hash}"
            )
            approved_status = ApprovalStatus.UNAPPROVED
            service.enabled = False
        
        # Create new snapshot record
        new_snapshot = MCPSnapshot(
            service_id=service.id,
            snapshot_json=snapshot_result.snapshot_json,
            snapshot_hash=snapshot_result.snapshot_hash,
            approved_status=approved_status,
        )
        session.add(new_snapshot)
        
        await session.commit()
        
        logger.info(f"Check complete for {service.name}: {approved_status.value}")
        
        # Return True if enabled status changed
        return original_enabled != service.enabled
    
    except Exception as e:
        logger.error(f"Failed to check service {service.name}: {e}", exc_info=True)
        # On error, we don't disable - just skip this check cycle
        return False


async def check_scheduler():
    """
    Periodically check services that are due for capability validation.
    
    Runs every scheduler_interval_seconds (default 60s).
    """
    logger.info("Check scheduler started")
    
    while True:
        try:
            async with AsyncSessionLocal() as session:
                # Get all enabled services with check_frequency > 0
                result = await session.execute(
                    select(MCPService).where(
                        MCPService.enabled == True,
                        MCPService.check_frequency_minutes > 0
                    )                )
                services = result.scalars().all()
                
                logger.debug(f"Found {len(services)} services to potentially check")
                
                # Track if any service routing changed during checks
                routes_changed = False
                
                # Check each service
                for service in services:
                    # Get last snapshot time
                    last_snapshot_result = await session.execute(
                        select(MCPSnapshot)
                        .where(MCPSnapshot.service_id == service.id)
                        .order_by(desc(MCPSnapshot.created_at))
                        .limit(1)
                    )
                    last_snapshot = last_snapshot_result.scalar_one_or_none()
                    last_check_time = last_snapshot.created_at if last_snapshot else None
                    
                    # Check if due
                    if await is_check_due(service, last_check_time):
                        logger.info(f"Service {service.name} is due for check")
                        service_changed = await check_service(service, session)
                        if service_changed:
                            routes_changed = True
                
                # Only reload route registry if any service routing changed
                if routes_changed:
                    logger.info("Service routing changed, reloading route registry")
                    all_services_result = await session.execute(select(MCPService))
                    all_services = all_services_result.scalars().all()
                    await route_registry.reload(all_services)
        
        except Exception as e:
            logger.error(f"Error in check scheduler: {e}", exc_info=True)
        
        # Sleep for configured interval
        await asyncio.sleep(settings.scheduler_interval_seconds)
