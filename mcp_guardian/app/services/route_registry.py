"""In-memory route registry backed by database."""
import asyncio
import logging
from typing import Dict, Set

logger = logging.getLogger(__name__)


class RouteRegistry:
    """
    In-memory registry of all MCP service routes.
    
    This is refreshed periodically from the database by the route poller.    Using an in-memory registry avoids hot route surgery in FastAPI.
    """
    
    def __init__(self):
        """Initialize the route registry."""
        self._enabled_services: Set[str] = set()
        self._all_services: Dict[str, str] = {}  # Maps service_name -> upstream_url for ALL services
        self._lock = asyncio.Lock()
    
    async def reload(self, services: list) -> None:
        """
        Reload the registry from a list of service objects.
        
        Args:
            services: List of MCPService objects from database
        """
        async with self._lock:
            self._enabled_services.clear()
            self._all_services.clear()
            
            for service in services:
                # Track ALL services (enabled or disabled)
                self._all_services[service.name] = service.upstream_url
                
                # Track only enabled services
                if service.enabled:
                    self._enabled_services.add(service.name)
            
            logger.info(f"Route registry reloaded: {len(self._enabled_services)} enabled services, {len(self._all_services)} total services")
    
    async def is_enabled(self, service_name: str) -> bool:
        """
        Check if a service route is enabled.
        
        Args:
            service_name: Name of the service
        
        Returns:
            True if service is enabled, False otherwise
        """
        async with self._lock:
            return service_name in self._enabled_services
    
    async def get_upstream_url(self, service_name: str) -> str | None:
        """
        Get the upstream URL for a service (enabled or disabled).
        
        Args:
            service_name: Name of the service
        
        Returns:
            Upstream URL or None if service doesn't exist at all
        """
        async with self._lock:
            return self._all_services.get(service_name)
    
    async def service_exists(self, service_name: str) -> bool:
        """
        Check if a service exists in the registry (enabled or disabled).
        
        Args:
            service_name: Name of the service
        
        Returns:
            True if service exists, False otherwise
        """
        async with self._lock:
            return service_name in self._all_services
    
    async def get_enabled_services(self) -> list[str]:
        """
        Get list of all enabled service names.
        
        Returns:
            List of enabled service names
        """
        async with self._lock:
            return list(self._enabled_services)


# Global singleton instance
route_registry = RouteRegistry()
