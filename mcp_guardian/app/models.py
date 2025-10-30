"""SQLAlchemy ORM models for MCP Guardian."""
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey, Text, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class ApprovalStatus(PyEnum):
    """Approval status for snapshots."""
    USER_APPROVED = "user_approved"
    SYSTEM_APPROVED = "system_approved"
    UNAPPROVED = "unapproved"


class MCPService(Base):
    """MCP service configuration."""
    __tablename__ = "mcp_services"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    upstream_url: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    check_frequency_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, 
        default=datetime.utcnow, 
        onupdate=datetime.utcnow, 
        nullable=False
    )
    
    # Relationships
    snapshots: Mapped[list["MCPSnapshot"]] = relationship(
        "MCPSnapshot", 
        back_populates="service",
        cascade="all, delete-orphan"
    )
    
    def __repr__(self) -> str:
        return f"<MCPService(name={self.name}, enabled={self.enabled})>"


class MCPSnapshot(Base):
    """Snapshot of MCP server capabilities."""
    __tablename__ = "mcp_snapshots"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    service_id: Mapped[int] = mapped_column(
        Integer, 
        ForeignKey("mcp_services.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    approved_status: Mapped[ApprovalStatus] = mapped_column(
        Enum(ApprovalStatus),
        default=ApprovalStatus.UNAPPROVED,
        nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    service: Mapped["MCPService"] = relationship("MCPService", back_populates="snapshots")
    
    def __repr__(self) -> str:
        return f"<MCPSnapshot(service_id={self.service_id}, hash={self.snapshot_hash[:8]}...)>"


class AuditLog(Base):
    """Optional audit log for tracking actions."""
    __tablename__ = "audit_log"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    actor: Mapped[str] = mapped_column(String(50), nullable=False)  # "system" or "user"
    action: Mapped[str] = mapped_column(String(255), nullable=False)
    details_json: Mapped[str] = mapped_column(Text, nullable=True)
    
    def __repr__(self) -> str:
        return f"<AuditLog(actor={self.actor}, action={self.action})>"
