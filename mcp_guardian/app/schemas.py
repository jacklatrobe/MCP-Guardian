"""Pydantic schemas for request/response validation."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, HttpUrl

from .models import ApprovalStatus


# Service schemas
class ServiceCreate(BaseModel):
    """Schema for creating a new service."""
    name: str = Field(..., min_length=1, max_length=255, pattern=r"^[a-zA-Z0-9_-]+$")
    upstream_url: str = Field(..., min_length=1)
    enabled: bool = True
    check_frequency_minutes: int = Field(default=0, ge=0)


class ServiceUpdate(BaseModel):
    """Schema for updating a service."""
    upstream_url: Optional[str] = None
    enabled: Optional[bool] = None
    check_frequency_minutes: Optional[int] = Field(default=None, ge=0)


class ServiceResponse(BaseModel):
    """Schema for service response."""
    id: int
    name: str
    upstream_url: str
    enabled: bool
    check_frequency_minutes: int
    created_at: datetime
    updated_at: datetime
    
    model_config = {"from_attributes": True}


class ServiceWithStatus(ServiceResponse):
    """Service response with latest snapshot status."""
    latest_snapshot_status: Optional[ApprovalStatus] = None
    latest_snapshot_created_at: Optional[datetime] = None
    latest_approved_hash: Optional[str] = None


# Snapshot schemas
class SnapshotResponse(BaseModel):
    """Schema for snapshot response."""
    id: int
    service_id: int
    snapshot_json: str
    snapshot_hash: str
    approved_status: ApprovalStatus
    created_at: datetime
    
    model_config = {"from_attributes": True}


class SnapshotSummary(BaseModel):
    """Lightweight snapshot summary."""
    id: int
    snapshot_hash: str
    approved_status: ApprovalStatus
    created_at: datetime
    
    model_config = {"from_attributes": True}


# Diff schema
class DiffResponse(BaseModel):
    """Schema for diff response."""
    service_name: str
    approved_snapshot: Optional[SnapshotSummary] = None
    latest_snapshot: Optional[SnapshotSummary] = None
    diff: Optional[dict] = None  # JSON diff structure


# Approve schema
class ApproveResponse(BaseModel):
    """Schema for approve action response."""
    service_name: str
    snapshot_id: int
    new_status: ApprovalStatus
    enabled: bool
