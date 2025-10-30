"""Admin API endpoints for managing MCP services."""
import logging
from typing import List, Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import get_db
from ..models import MCPService, MCPSnapshot, ApprovalStatus
from ..schemas import (
    ServiceCreate,
    ServiceUpdate,
    ServiceResponse,
    ServiceWithStatus,
    SnapshotResponse,
    SnapshotSummary,
    DiffResponse,
    ApproveResponse,
)
from ..services.snapshotter import take_snapshot
from ..services.route_registry import route_registry
from ..services.diff import json_diff
from ..security import get_current_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/services", response_model=ServiceResponse, dependencies=[Depends(get_current_admin)])
async def create_service(
    service: ServiceCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new MCP service and take initial snapshot.
    
    This triggers initialization and capability listing.
    """
    logger.info(f"Creating service: {service.name}")
    
    # Check if service already exists
    result = await db.execute(
        select(MCPService).where(MCPService.name == service.name)
    )
    existing = result.scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail=f"Service '{service.name}' already exists")
    
    # Validate check frequency
    if service.check_frequency_minutes > 0 and service.check_frequency_minutes < settings.min_check_frequency:
        raise HTTPException(
            status_code=400,
            detail=f"Check frequency must be 0 or >= {settings.min_check_frequency} minutes"
        )
    
    # Take initial snapshot
    try:
        snapshot_result = await take_snapshot(service.upstream_url)
    except Exception as e:
        logger.error(f"Failed to snapshot {service.upstream_url}: {e}")
        raise HTTPException(status_code=400, detail=f"Failed to snapshot upstream server: {str(e)}")
    
    # Create service
    db_service = MCPService(
        name=service.name,
        upstream_url=service.upstream_url,
        enabled=service.enabled,
        check_frequency_minutes=service.check_frequency_minutes,
    )
    db.add(db_service)
    await db.flush()
    
    # Create initial snapshot
    db_snapshot = MCPSnapshot(
        service_id=db_service.id,
        snapshot_json=snapshot_result.snapshot_json,
        snapshot_hash=snapshot_result.snapshot_hash,
        approved_status=ApprovalStatus.USER_APPROVED,
    )
    db.add(db_snapshot)
    
    await db.commit()
    await db.refresh(db_service)
    
    # Reload route registry
    services = await db.execute(select(MCPService))
    await route_registry.reload(services.scalars().all())
    
    logger.info(f"Service created: {service.name} (hash: {snapshot_result.snapshot_hash})")
    
    return db_service


@router.get("/services", response_model=List[ServiceWithStatus], dependencies=[Depends(get_current_admin)])
async def list_services(db: AsyncSession = Depends(get_db)):
    """List all MCP services with their latest snapshot status."""
    result = await db.execute(select(MCPService).order_by(MCPService.name))
    services = result.scalars().all()
    
    response = []
    for service in services:
        # Get latest snapshot
        snapshot_result = await db.execute(
            select(MCPSnapshot)
            .where(MCPSnapshot.service_id == service.id)
            .order_by(desc(MCPSnapshot.created_at))
            .limit(1)
        )
        latest_snapshot = snapshot_result.scalar_one_or_none()
        
        # Get latest approved snapshot
        approved_result = await db.execute(
            select(MCPSnapshot)
            .where(
                MCPSnapshot.service_id == service.id,
                MCPSnapshot.approved_status.in_([ApprovalStatus.USER_APPROVED, ApprovalStatus.SYSTEM_APPROVED])
            )
            .order_by(desc(MCPSnapshot.created_at))
            .limit(1)
        )
        approved_snapshot = approved_result.scalar_one_or_none()
        
        service_dict = {
            "id": service.id,
            "name": service.name,
            "upstream_url": service.upstream_url,
            "enabled": service.enabled,
            "check_frequency_minutes": service.check_frequency_minutes,
            "created_at": service.created_at,
            "updated_at": service.updated_at,
            "latest_snapshot_status": latest_snapshot.approved_status if latest_snapshot else None,
            "latest_snapshot_created_at": latest_snapshot.created_at if latest_snapshot else None,
            "latest_approved_hash": approved_snapshot.snapshot_hash if approved_snapshot else None,
        }
        response.append(service_dict)
    
    return response


@router.get("/services/{name}", response_model=ServiceWithStatus, dependencies=[Depends(get_current_admin)])
async def get_service(name: str, db: AsyncSession = Depends(get_db)):
    """Get a specific service by name."""
    result = await db.execute(select(MCPService).where(MCPService.name == name))
    service = result.scalar_one_or_none()
    
    if not service:
        raise HTTPException(status_code=404, detail=f"Service '{name}' not found")
    
    # Get latest snapshot
    snapshot_result = await db.execute(
        select(MCPSnapshot)
        .where(MCPSnapshot.service_id == service.id)
        .order_by(desc(MCPSnapshot.created_at))
        .limit(1)
    )
    latest_snapshot = snapshot_result.scalar_one_or_none()
    
    # Get latest approved snapshot
    approved_result = await db.execute(
        select(MCPSnapshot)
        .where(
            MCPSnapshot.service_id == service.id,
            MCPSnapshot.approved_status.in_([ApprovalStatus.USER_APPROVED, ApprovalStatus.SYSTEM_APPROVED])
        )
        .order_by(desc(MCPSnapshot.created_at))
        .limit(1)
    )
    approved_snapshot = approved_result.scalar_one_or_none()
    
    service_dict = {
        "id": service.id,
        "name": service.name,
        "upstream_url": service.upstream_url,
        "enabled": service.enabled,
        "check_frequency_minutes": service.check_frequency_minutes,
        "created_at": service.created_at,
        "updated_at": service.updated_at,
        "latest_snapshot_status": latest_snapshot.approved_status if latest_snapshot else None,
        "latest_snapshot_created_at": latest_snapshot.created_at if latest_snapshot else None,
        "latest_approved_hash": approved_snapshot.snapshot_hash if approved_snapshot else None,
    }
    
    return service_dict


@router.patch("/services/{name}", response_model=ServiceResponse, dependencies=[Depends(get_current_admin)])
async def update_service(
    name: str,
    update: ServiceUpdate,
    db: AsyncSession = Depends(get_db),
):
    """
    Update a service configuration.
    
    If upstream_url changes, a new snapshot is required before re-enabling.
    """
    result = await db.execute(select(MCPService).where(MCPService.name == name))
    service = result.scalar_one_or_none()
    
    if not service:
        raise HTTPException(status_code=404, detail=f"Service '{name}' not found")
    
    url_changed = False
    
    if update.upstream_url is not None:
        if update.upstream_url != service.upstream_url:
            url_changed = True
            service.upstream_url = update.upstream_url
    
    if update.enabled is not None:
        service.enabled = update.enabled
    
    if update.check_frequency_minutes is not None:
        if update.check_frequency_minutes > 0 and update.check_frequency_minutes < settings.min_check_frequency:
            raise HTTPException(
                status_code=400,
                detail=f"Check frequency must be 0 or >= {settings.min_check_frequency} minutes"
            )
        service.check_frequency_minutes = update.check_frequency_minutes
    
    # If URL changed, take new snapshot and mark as unapproved
    if url_changed:
        logger.info(f"Service {name} URL changed, taking new snapshot")
        try:
            snapshot_result = await take_snapshot(service.upstream_url)
            
            db_snapshot = MCPSnapshot(
                service_id=service.id,
                snapshot_json=snapshot_result.snapshot_json,
                snapshot_hash=snapshot_result.snapshot_hash,
                approved_status=ApprovalStatus.UNAPPROVED,
            )
            db.add(db_snapshot)
            
            # Auto-disable if URL changed
            service.enabled = False
        except Exception as e:
            logger.error(f"Failed to snapshot {service.upstream_url}: {e}")
            raise HTTPException(status_code=400, detail=f"Failed to snapshot updated URL: {str(e)}")
    
    await db.commit()
    await db.refresh(service)
    
    # Reload route registry
    services = await db.execute(select(MCPService))
    await route_registry.reload(services.scalars().all())
    
    return service


@router.delete("/services/{name}", dependencies=[Depends(get_current_admin)])
async def delete_service(name: str, db: AsyncSession = Depends(get_db)):
    """Delete a service and all its snapshots."""
    result = await db.execute(select(MCPService).where(MCPService.name == name))
    service = result.scalar_one_or_none()
    
    if not service:
        raise HTTPException(status_code=404, detail=f"Service '{name}' not found")
    
    await db.delete(service)
    await db.commit()
    
    # Reload route registry
    services = await db.execute(select(MCPService))
    await route_registry.reload(services.scalars().all())
    
    logger.info(f"Service deleted: {name}")
    
    return {"status": "deleted", "name": name}


@router.get("/services/{name}/snapshots", response_model=List[SnapshotSummary], dependencies=[Depends(get_current_admin)])
async def list_snapshots(name: str, limit: int = 10, db: AsyncSession = Depends(get_db)):
    """List recent snapshots for a service."""
    result = await db.execute(select(MCPService).where(MCPService.name == name))
    service = result.scalar_one_or_none()
    
    if not service:
        raise HTTPException(status_code=404, detail=f"Service '{name}' not found")
    
    snapshots_result = await db.execute(
        select(MCPSnapshot)
        .where(MCPSnapshot.service_id == service.id)
        .order_by(desc(MCPSnapshot.created_at))
        .limit(limit)
    )
    snapshots = snapshots_result.scalars().all()
    
    return [
        SnapshotSummary(
            id=s.id,
            snapshot_hash=s.snapshot_hash,
            approved_status=s.approved_status,
            created_at=s.created_at,
        )
        for s in snapshots    ]


@router.get("/services/{name}/snapshots/latest", response_model=SnapshotResponse, dependencies=[Depends(get_current_admin)])
async def get_latest_snapshot(name: str, db: AsyncSession = Depends(get_db)):
    """Get the latest snapshot for a service including full JSON data."""
    result = await db.execute(select(MCPService).where(MCPService.name == name))
    service = result.scalar_one_or_none()
    
    if not service:
        raise HTTPException(status_code=404, detail=f"Service '{name}' not found")
    
    snapshot_result = await db.execute(
        select(MCPSnapshot)
        .where(MCPSnapshot.service_id == service.id)
        .order_by(desc(MCPSnapshot.created_at))
        .limit(1)
    )
    snapshot = snapshot_result.scalar_one_or_none()
    
    if not snapshot:
        raise HTTPException(status_code=404, detail=f"No snapshots found for service '{name}'")
    
    return snapshot


@router.get("/services/{name}/snapshots/{snapshot_id}", response_model=SnapshotResponse, dependencies=[Depends(get_current_admin)])
async def get_snapshot(name: str, snapshot_id: int, db: AsyncSession = Depends(get_db)):
    """Get full details of a specific snapshot including JSON data."""
    logger.info(f"Getting snapshot {snapshot_id} for service '{name}'")
    
    result = await db.execute(select(MCPService).where(MCPService.name == name))
    service = result.scalar_one_or_none()
    
    if not service:
        logger.warning(f"Service '{name}' not found")
        raise HTTPException(status_code=404, detail=f"Service '{name}' not found")
    
    logger.info(f"Found service with id={service.id}")
    
    snapshot_result = await db.execute(
        select(MCPSnapshot)
        .where(
            MCPSnapshot.id == snapshot_id,
            MCPSnapshot.service_id == service.id
        )
    )
    snapshot = snapshot_result.scalar_one_or_none()
    
    if not snapshot:
        # Try to find if snapshot exists at all
        check_result = await db.execute(
            select(MCPSnapshot).where(MCPSnapshot.id == snapshot_id)
        )
        existing_snapshot = check_result.scalar_one_or_none()
        
        if existing_snapshot:
            logger.warning(f"Snapshot {snapshot_id} exists but belongs to service_id={existing_snapshot.service_id}, not service_id={service.id}")
            raise HTTPException(status_code=404, detail=f"Snapshot {snapshot_id} does not belong to service '{name}'")
        else:
            logger.warning(f"Snapshot {snapshot_id} does not exist at all")
            raise HTTPException(status_code=404, detail=f"Snapshot {snapshot_id} not found")
    
    logger.info(f"Found snapshot {snapshot_id} with hash {snapshot.snapshot_hash[:16]}...")
    return snapshot


@router.get("/services/{name}/diff", response_model=DiffResponse, dependencies=[Depends(get_current_admin)])
async def get_diff(name: str, db: AsyncSession = Depends(get_db)):
    """Get diff between last approved snapshot and latest snapshot."""
    result = await db.execute(select(MCPService).where(MCPService.name == name))
    service = result.scalar_one_or_none()
    
    if not service:
        raise HTTPException(status_code=404, detail=f"Service '{name}' not found")
    
    # Get latest approved snapshot
    approved_result = await db.execute(
        select(MCPSnapshot)
        .where(
            MCPSnapshot.service_id == service.id,
            MCPSnapshot.approved_status.in_([ApprovalStatus.USER_APPROVED, ApprovalStatus.SYSTEM_APPROVED])
        )
        .order_by(desc(MCPSnapshot.created_at))
        .limit(1)
    )
    approved_snapshot = approved_result.scalar_one_or_none()
    
    # Get latest snapshot
    latest_result = await db.execute(
        select(MCPSnapshot)
        .where(MCPSnapshot.service_id == service.id)
        .order_by(desc(MCPSnapshot.created_at))
        .limit(1)
    )
    latest_snapshot = latest_result.scalar_one_or_none()
    
    diff_result = None
    if approved_snapshot and latest_snapshot and approved_snapshot.id != latest_snapshot.id:
        diff_result = json_diff(approved_snapshot.snapshot_json, latest_snapshot.snapshot_json)
    
    return DiffResponse(
        service_name=name,
        approved_snapshot=SnapshotSummary(
            id=approved_snapshot.id,
            snapshot_hash=approved_snapshot.snapshot_hash,
            approved_status=approved_snapshot.approved_status,
            created_at=approved_snapshot.created_at,
        ) if approved_snapshot else None,
        latest_snapshot=SnapshotSummary(
            id=latest_snapshot.id,
            snapshot_hash=latest_snapshot.snapshot_hash,
            approved_status=latest_snapshot.approved_status,
            created_at=latest_snapshot.created_at,
        ) if latest_snapshot else None,
        diff=diff_result,
    )


@router.post("/services/{name}/approve", response_model=ApproveResponse, dependencies=[Depends(get_current_admin)])
async def approve_latest_snapshot(name: str, db: AsyncSession = Depends(get_db)):
    """
    Approve the latest snapshot and optionally re-enable the service.
    
    This marks the latest snapshot as USER_APPROVED.
    """
    result = await db.execute(select(MCPService).where(MCPService.name == name))
    service = result.scalar_one_or_none()
    
    if not service:
        raise HTTPException(status_code=404, detail=f"Service '{name}' not found")
    
    # Get latest snapshot
    latest_result = await db.execute(
        select(MCPSnapshot)
        .where(MCPSnapshot.service_id == service.id)
        .order_by(desc(MCPSnapshot.created_at))
        .limit(1)
    )
    latest_snapshot = latest_result.scalar_one_or_none()
    
    if not latest_snapshot:
        raise HTTPException(status_code=404, detail=f"No snapshots found for service '{name}'")
    
    # Mark as user approved
    latest_snapshot.approved_status = ApprovalStatus.USER_APPROVED
    
    # Re-enable service (admin can disable again via PATCH if desired)
    service.enabled = True
    
    await db.commit()
    
    # Reload route registry
    services = await db.execute(select(MCPService))
    await route_registry.reload(services.scalars().all())
    
    logger.info(f"Snapshot approved and service re-enabled: {name}")
    
    return ApproveResponse(
        service_name=name,
        snapshot_id=latest_snapshot.id,
        new_status=ApprovalStatus.USER_APPROVED,
        enabled=True,
    )


@router.get("/services/{name}/client-config", dependencies=[Depends(get_current_admin)])
async def get_client_config(name: str, db: AsyncSession = Depends(get_db)):
    """Get MCP client configuration snippet for a service."""
    result = await db.execute(select(MCPService).where(MCPService.name == name))
    service = result.scalar_one_or_none()
    
    if not service:
        raise HTTPException(status_code=404, detail=f"Service '{name}' not found")
    
    # Generate the client config
    mcp_url = f"{settings.base_url.rstrip('/')}/{service.name}/mcp"
    
    config = {
        service.name: {
            "url": mcp_url
        }
    }
    
    return {
        "service_name": service.name,
        "config": config,
        "config_string": f'"{service.name}": {{\n  "url": "{mcp_url}"\n}}'
    }
