"""MCP server snapshot functionality - initialize and list capabilities."""
import logging
from typing import Dict, Any, Tuple

from .proxy_client import ProxyClient
from .canonicalize import create_snapshot_hash

logger = logging.getLogger(__name__)


class SnapshotResult:
    """Result of taking a snapshot."""
    
    def __init__(
        self,
        snapshot_json: str,
        snapshot_hash: str,
        tools: list,
        resources: list,
        resource_templates: list,
        prompts: list,
    ):
        self.snapshot_json = snapshot_json
        self.snapshot_hash = snapshot_hash
        self.tools = tools
        self.resources = resources
        self.resource_templates = resource_templates
        self.prompts = prompts


async def initialize_server(url: str) -> Dict[str, Any]:
    """
    Initialize connection to an MCP server.
    
    Args:
        url: Upstream MCP endpoint URL
    
    Returns:
        Initialize response with server capabilities
    
    Raises:
        Exception: On initialization failure
    """
    async with ProxyClient() as client:
        logger.info(f"Initializing MCP server at {url}")
        
        # Send initialize request
        response = await client.send_jsonrpc(
            url,
            method="initialize",
            params={
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "roots": {"listChanged": False},
                    "sampling": {},
                },
                "clientInfo": {
                    "name": "mcp-guardian",
                    "version": "0.1.0",
                },
            },
        )
        
        if "result" not in response:
            raise ValueError(f"Initialize failed: no result in response")
        
        logger.info(f"Server initialized: {response['result'].get('serverInfo', {})}")
        return response["result"]


async def list_tools(url: str) -> list:
    """
    List all tools from an MCP server (with pagination support).
    
    Args:
        url: Upstream MCP endpoint URL
    
    Returns:
        List of all tools (empty list if not supported)
    """
    async with ProxyClient() as client:
        logger.debug(f"Listing tools from {url}")
        
        all_tools = []
        cursor = None
        
        while True:
            params = {}
            if cursor:
                params["cursor"] = cursor
            
            try:
                response = await client.send_jsonrpc(url, method="tools/list", params=params if params else None)
                
                # Check for JSON-RPC error (Method not found)
                if "error" in response:
                    error_code = response["error"].get("code")
                    if error_code == -32601:
                        logger.info(f"Server does not implement tools/list (Method not found)")
                        return []
                    logger.warning(f"tools/list returned error: {response['error']}")
                    break
                
                if "result" not in response:
                    logger.warning(f"tools/list returned no result")
                    break
                
                result = response["result"]
                tools = result.get("tools", [])
                all_tools.extend(tools)
                
                # Check for pagination
                cursor = result.get("nextCursor")
                if not cursor:
                    break
            except Exception as e:
                logger.debug(f"Failed to list tools (may not be supported): {e}")
                return []
        
        logger.info(f"Found {len(all_tools)} tools")
        return all_tools


async def list_resources(url: str) -> list:
    """
    List all resources from an MCP server (with pagination support).
    
    Args:
        url: Upstream MCP endpoint URL
    
    Returns:
        List of all resources (empty list if not supported)
    """
    async with ProxyClient() as client:
        logger.debug(f"Listing resources from {url}")
        
        all_resources = []
        cursor = None
        
        while True:
            params = {}
            if cursor:
                params["cursor"] = cursor
            
            try:
                response = await client.send_jsonrpc(url, method="resources/list", params=params if params else None)
                
                # Check for JSON-RPC error (Method not found)
                if "error" in response:
                    error_code = response["error"].get("code")
                    if error_code == -32601:
                        logger.info(f"Server does not implement resources/list (Method not found)")
                        return []
                    logger.warning(f"resources/list returned error: {response['error']}")
                    break
                
                if "result" not in response:
                    logger.warning(f"resources/list returned no result")
                    break
                
                result = response["result"]
                resources = result.get("resources", [])
                all_resources.extend(resources)
                
                # Check for pagination
                cursor = result.get("nextCursor")
                if not cursor:
                    break
            except Exception as e:
                logger.debug(f"Failed to list resources (may not be supported): {e}")
                return []
        
        logger.info(f"Found {len(all_resources)} resources")
        return all_resources


async def list_resource_templates(url: str) -> list:
    """
    List all resource templates from an MCP server.
    
    Args:
        url: Upstream MCP endpoint URL
    
    Returns:
        List of all resource templates
    """
    async with ProxyClient() as client:
        logger.debug(f"Listing resource templates from {url}")
        
        try:
            response = await client.send_jsonrpc(url, method="resources/templates/list")
            
            if "result" not in response:
                logger.warning(f"resources/templates/list returned no result")
                return []
            
            result = response["result"]
            templates = result.get("resourceTemplates", [])
            
            logger.info(f"Found {len(templates)} resource templates")
            return templates
        except Exception as e:
            # Resource templates might not be supported by all servers
            logger.debug(f"Failed to list resource templates (may not be supported): {e}")
            return []


async def list_prompts(url: str) -> list:
    """
    List all prompts from an MCP server (with pagination support).
    
    Args:
        url: Upstream MCP endpoint URL
    
    Returns:
        List of all prompts (empty list if not supported)
    """
    async with ProxyClient() as client:
        logger.debug(f"Listing prompts from {url}")
        
        all_prompts = []
        cursor = None
        
        while True:
            params = {}
            if cursor:
                params["cursor"] = cursor
            
            try:
                response = await client.send_jsonrpc(url, method="prompts/list", params=params if params else None)
                
                # Check for JSON-RPC error (Method not found)
                if "error" in response:
                    error_code = response["error"].get("code")
                    if error_code == -32601:
                        logger.info(f"Server does not implement prompts/list (Method not found)")
                        return []
                    logger.warning(f"prompts/list returned error: {response['error']}")
                    break
                
                if "result" not in response:
                    logger.warning(f"prompts/list returned no result")
                    break
                
                result = response["result"]
                prompts = result.get("prompts", [])
                all_prompts.extend(prompts)
                
                # Check for pagination
                cursor = result.get("nextCursor")
                if not cursor:
                    break
            except Exception as e:
                logger.debug(f"Failed to list prompts (may not be supported): {e}")
                return []
        
        logger.info(f"Found {len(all_prompts)} prompts")
        return all_prompts


async def take_snapshot(upstream_url: str) -> SnapshotResult:
    """
    Take a complete snapshot of an MCP server's capabilities.
    
    This includes:
    1. Initialize the server
    2. List tools, resources, resource templates, and prompts
    3. Create canonical JSON and hash
    
    Args:
        upstream_url: URL of the upstream MCP server
    
    Returns:
        SnapshotResult with canonical JSON and hash
    
    Raises:
        Exception: On any failure during snapshot
    """
    logger.info(f"Taking snapshot of {upstream_url}")
    
    # Step 1: Initialize
    await initialize_server(upstream_url)
    
    # Step 2: List all capabilities
    tools = await list_tools(upstream_url)
    resources = await list_resources(upstream_url)
    resource_templates = await list_resource_templates(upstream_url)
    prompts = await list_prompts(upstream_url)
    
    # Step 3: Create canonical JSON and hash
    canonical_json, snapshot_hash = create_snapshot_hash(
        tools=tools,
        resources=resources,
        resource_templates=resource_templates,
        prompts=prompts,
    )
    
    logger.info(f"Snapshot complete: hash={snapshot_hash}")
    
    return SnapshotResult(
        snapshot_json=canonical_json,
        snapshot_hash=snapshot_hash,
        tools=tools,
        resources=resources,
        resource_templates=resource_templates,
        prompts=prompts,
    )
