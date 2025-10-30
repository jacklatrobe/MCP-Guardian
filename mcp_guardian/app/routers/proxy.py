"""MCP proxy endpoint - transparent passthrough for all services."""
import logging

from fastapi import APIRouter, Request, Response, HTTPException
from fastapi.responses import StreamingResponse

from ..services.route_registry import route_registry
from ..services.proxy_client import ProxyClient

logger = logging.getLogger(__name__)

router = APIRouter()


# Headers that should NOT be forwarded (FastAPI/ASGI internal headers)
EXCLUDED_HEADERS = {
    "host",  # Will be set by httpx based on target URL
    "content-length",  # Will be recalculated
    "transfer-encoding",  # Will be handled by httpx
}


@router.post("/{service_name}/mcp")
async def proxy_post(service_name: str, request: Request):
    """
    Transparent proxy for POST requests to upstream MCP server.
    Just check if enabled, then forward everything as-is.
    """
    # Check if service exists at all
    if not await route_registry.service_exists(service_name):
        logger.warning(f"Request to unknown service: {service_name}")
        raise HTTPException(status_code=404, detail=f"Service '{service_name}' not found")
    
    # Check if service is enabled
    if not await route_registry.is_enabled(service_name):
        logger.warning(f"Request to disabled service: {service_name}")
        raise HTTPException(
            status_code=403,
            detail=f"Service '{service_name}' is currently disabled pending review"
        )
      # Get upstream URL
    upstream_url = await route_registry.get_upstream_url(service_name)
    if not upstream_url:
        # This should never happen since we checked service_exists above
        raise HTTPException(status_code=500, detail="Internal error: service URL not found")
    
    # Forward ALL headers except excluded ones
    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in EXCLUDED_HEADERS
    }
    
    # Read body as-is
    body = await request.body()
    
    logger.debug(f"Proxying POST to {service_name}: {upstream_url}")
    
    # Forward request and stream response back unchanged
    async with ProxyClient() as client:
        try:
            response = await client.forward_post(upstream_url, body, headers)
            
            # Forward ALL response headers
            response_headers = {
                k: v for k, v in response.headers.items()
                if k.lower() not in EXCLUDED_HEADERS
            }
            
            # Stream response back unchanged
            async def stream_response():
                try:
                    async for chunk in response.aiter_bytes():
                        yield chunk
                finally:
                    await response.aclose()
            
            return StreamingResponse(
                stream_response(),
                status_code=response.status_code,
                headers=response_headers,
                media_type=response.headers.get("content-type"),
            )
        
        except Exception as e:
            logger.error(f"Error proxying to {service_name}: {e}")
            raise HTTPException(status_code=502, detail=f"Upstream error: {str(e)}")


@router.get("/{service_name}/mcp")
async def proxy_get(service_name: str, request: Request):
    """
    Transparent proxy for GET requests to upstream MCP server.
    Just check if enabled, then forward everything as-is.
    """
    # Check if service exists at all
    if not await route_registry.service_exists(service_name):
        logger.warning(f"GET request to unknown service: {service_name}")
        raise HTTPException(status_code=404, detail=f"Service '{service_name}' not found")
    
    # Check if service is enabled
    if not await route_registry.is_enabled(service_name):
        logger.warning(f"GET request to disabled service: {service_name}")
        raise HTTPException(
            status_code=403,
            detail=f"Service '{service_name}' is currently disabled pending review"
        )
    
    # Get upstream URL
    upstream_url = await route_registry.get_upstream_url(service_name)
    if not upstream_url:
        raise HTTPException(status_code=404, detail=f"Service '{service_name}' not found")
    
    # Forward ALL headers except excluded ones
    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in EXCLUDED_HEADERS
    }
    
    logger.debug(f"Proxying GET to {service_name}: {upstream_url}")
    
    # Forward request and stream response back unchanged
    async with ProxyClient() as client:
        try:
            response = await client.forward_get_check(upstream_url, headers)
            
            # Forward ALL response headers
            response_headers = {
                k: v for k, v in response.headers.items()
                if k.lower() not in EXCLUDED_HEADERS
            }
            
            # Stream response back unchanged
            async def stream_response():
                try:
                    async for chunk in response.aiter_bytes():
                        yield chunk
                finally:
                    await response.aclose()
            
            return StreamingResponse(
                stream_response(),
                status_code=response.status_code,
                headers=response_headers,
                media_type=response.headers.get("content-type"),
            )
        
        except Exception as e:
            logger.error(f"Error proxying GET to {service_name}: {e}")
            raise HTTPException(status_code=502, detail=f"Upstream error: {str(e)}")


@router.delete("/{service_name}/mcp")
async def proxy_delete(service_name: str, request: Request):
    """
    Transparent proxy for DELETE requests to upstream MCP server.
    Just check if enabled, then forward everything as-is.
    """
    # Check if service exists at all
    if not await route_registry.service_exists(service_name):
        logger.warning(f"DELETE request to unknown service: {service_name}")
        raise HTTPException(status_code=404, detail=f"Service '{service_name}' not found")
    
    # Check if service is enabled
    if not await route_registry.is_enabled(service_name):
        logger.warning(f"DELETE request to disabled service: {service_name}")
        raise HTTPException(
            status_code=403,
            detail=f"Service '{service_name}' is currently disabled pending review"
        )
    
    # Get upstream URL
    upstream_url = await route_registry.get_upstream_url(service_name)
    if not upstream_url:
        raise HTTPException(status_code=404, detail=f"Service '{service_name}' not found")
    
    # Forward ALL headers except excluded ones
    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in EXCLUDED_HEADERS
    }
    
    logger.debug(f"Proxying DELETE to {service_name}: {upstream_url}")
    
    # Forward request
    async with ProxyClient() as client:
        try:
            response = await client.forward_delete(upstream_url, headers)
            
            # Forward ALL response headers
            response_headers = {
                k: v for k, v in response.headers.items()
                if k.lower() not in EXCLUDED_HEADERS
            }
            
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=response_headers,
                media_type=response.headers.get("content-type"),
            )
        
        except Exception as e:
            logger.error(f"Error proxying DELETE to {service_name}: {e}")
            raise HTTPException(status_code=502, detail=f"Upstream error: {str(e)}")
