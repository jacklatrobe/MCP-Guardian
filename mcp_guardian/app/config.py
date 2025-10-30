"""Configuration management from config.yml."""
import logging
import secrets
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class AdminConfig(BaseModel):
    """Admin interface configuration."""
    password: Optional[str] = None
    disable_ui: bool = False


class PollingConfig(BaseModel):
    """Polling and scheduling configuration."""
    interval_seconds: int = 60
    min_check_frequency: int = 5


class DatabaseConfig(BaseModel):
    """Database configuration."""
    url: str = "sqlite+aiosqlite:///./mcp_guardian.db"


class ServiceConfig(BaseModel):
    """Pre-configured service definition."""
    name: str
    upstream_url: str
    enabled: bool = True
    check_frequency_minutes: int = 0


class Settings:
    """Application settings loaded from config.yml."""
    
    def __init__(self):
        self.config_path = Path("config.yml")
        self.config_data = self._load_config()
        
        # Parse configuration sections
        self.admin = AdminConfig(**self.config_data.get("admin", {}))
        self.polling = PollingConfig(**self.config_data.get("polling", {}))
        self.database = DatabaseConfig(**self.config_data.get("database", {}))
        self.services: list[ServiceConfig] = [
            ServiceConfig(**svc) for svc in self.config_data.get("services", [])
        ]
        
        # Server settings (defaults, can be overridden by env or CLI)
        self.host: str = "0.0.0.0"
        self.port: int = 8000
        self.log_level: str = "INFO"
        
        # Base URL for MCP Guardian (used in client configs)
        self.base_url: str = self.config_data.get("base_url", "http://localhost:8000")
        
        # Runtime: generate random password if not provided
        self.admin_password: str = self._get_admin_password()
    
    def _load_config(self) -> dict:
        """Load configuration from config.yml if it exists."""
        if self.config_path.exists():
            with open(self.config_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        return {}
    
    def _get_admin_password(self) -> str:
        """Get admin password from config or generate a random one."""
        if self.admin.password:
            # Strip whitespace that might come from YAML parsing
            return self.admin.password.strip()
        
        # Generate a random password
        random_password = secrets.token_urlsafe(16)
        return random_password
    
    @property
    def database_url(self) -> str:
        """Get database URL."""
        return self.database.url
    
    @property
    def scheduler_interval_seconds(self) -> int:
        """Get scheduler interval."""
        return self.polling.interval_seconds
    
    @property
    def min_check_frequency(self) -> int:
        """Get minimum check frequency."""
        return self.polling.min_check_frequency


settings = Settings()
