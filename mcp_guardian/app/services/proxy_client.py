"""HTTP client for upstream MCP server interactions using httpx."""
import json
import logging
from typing import Any, Dict, Optional, AsyncIterator

import httpx
from httpx_sse import aconnect_sse

logger = logging.getLogger(__name__)


class ProxyClient:
    """Client for communicating with upstream MCP servers."""
    
    def __init__(self, timeout: float = 30.0):
        """
        Initialize the proxy client.
        
        Args:
            timeout: Default timeout for requests in seconds
        """
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None
    
    async def __aenter__(self):
        """Async context manager entry."""
        self._client = httpx.AsyncClient(timeout=self.timeout)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self._client:
            await self._client.aclose()
    
    def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client
    
    async def close(self):
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
    
    async def send_jsonrpc(
        self,
        url: str,
        method: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Send a JSON-RPC 2.0 request to an MCP server.
        
        Args:
            url: Upstream MCP endpoint URL
            method: JSON-RPC method name
            params: Optional parameters
            headers: Optional additional headers
        
        Returns:
            JSON-RPC response as dictionary
        
        Raises:
            httpx.HTTPError: On network errors
            ValueError: On invalid JSON-RPC response
        """
        client = self._get_client()
          # Build JSON-RPC 2.0 request
        jsonrpc_request = {
            "jsonrpc": "2.0",
            "id": 1,  # Simple sequential ID for now
            "method": method,
        }
        if params:
            jsonrpc_request["params"] = params
        
        # Prepare headers - MCP spec requires both content types in Accept header
        # Also include MCP-Protocol-Version header as recommended
        request_headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2024-11-05",
        }
        if headers:
            request_headers.update(headers)
        
        logger.debug(f"Sending JSON-RPC to {url}: {method}")
          # Send request
        response = await client.post(
            url,
            json=jsonrpc_request,
            headers=request_headers,
        )
        response.raise_for_status()
          # Check response content type
        content_type = response.headers.get("content-type", "").lower()        # Handle SSE response (server chose to stream)
        if "text/event-stream" in content_type:
            # For SSE responses, we need to collect events until we get the JSON-RPC response
            logger.debug(f"Received SSE response for {method}, collecting events...")
            
            # Manually parse SSE stream from response
            # SSE format: "data: <json>\n\n" or multi-line "data: line1\ndata: line2\n\n"
            buffer = ""
            async for chunk in response.aiter_bytes():
                buffer += chunk.decode("utf-8")
                
                # Process complete events (terminated by double newline)
                while "\n\n" in buffer:
                    event_text, buffer = buffer.split("\n\n", 1)
                    
                    # Extract data lines from event
                    data_lines = []
                    for line in event_text.split("\n"):
                        if line.startswith("data: "):
                            data_lines.append(line[6:])  # Strip "data: " prefix
                    
                    if data_lines:
                        event_data = "\n".join(data_lines)
                        try:
                            # Try to parse as JSON-RPC response
                            data = json.loads(event_data)
                            
                            # Check if it's a JSON-RPC response (not request/notification)
                            if "result" in data or "error" in data:
                                # Validate JSON-RPC response
                                if "jsonrpc" not in data or data["jsonrpc"] != "2.0":
                                    raise ValueError(f"Invalid JSON-RPC response: {data}")
                                
                                if "error" in data:
                                    error = data["error"]
                                    raise ValueError(f"JSON-RPC error {error.get('code')}: {error.get('message')}")
                                
                                return data
                        except json.JSONDecodeError:
                            # Not JSON, continue to next event
                            continue
            
            raise ValueError("No JSON-RPC response found in SSE stream")
        
        # Handle regular JSON response
        try:
            data = response.json()
        except Exception as e:
            logger.error(f"Failed to parse JSON response from {url}: {e}")
            logger.error(f"Response status: {response.status_code}")
            logger.error(f"Response headers: {dict(response.headers)}")
            logger.error(f"Response body: {response.text[:500]}")  # Log first 500 chars
            raise ValueError(f"Invalid response from server: {str(e)}")
        
        # Validate JSON-RPC response
        if "jsonrpc" not in data or data["jsonrpc"] != "2.0":
            raise ValueError(f"Invalid JSON-RPC response: {data}")
        
        if "error" in data:
            error = data["error"]
            raise ValueError(f"JSON-RPC error {error.get('code')}: {error.get('message')}")
        
        return data
    
    async def forward_post(
        self,
        url: str,
        body: bytes,
        headers: Dict[str, str],
    ) -> httpx.Response:
        """
        Forward a POST request to upstream MCP server.
        
        Args:
            url: Upstream MCP endpoint URL
            body: Raw request body
            headers: Request headers to forward
        
        Returns:
            Raw httpx Response object (may be JSON or SSE stream)
        """
        client = self._get_client()
        
        logger.debug(f"Forwarding POST to {url}")
        
        response = await client.post(
            url,
            content=body,
            headers=headers,
        )
        return response
    
    async def forward_get_sse(
        self,
        url: str,
        headers: Dict[str, str],
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Forward a GET request for SSE streaming from upstream.
        
        Args:
            url: Upstream MCP endpoint URL
            headers: Request headers to forward (including Last-Event-ID if present)
        
        Yields:
            SSE events as dictionaries with 'event', 'data', 'id' fields
        """
        client = self._get_client()
        
        logger.debug(f"Forwarding GET (SSE) to {url}")
        
        async with aconnect_sse(client, "GET", url, headers=headers) as event_source:
            async for sse in event_source.aiter_sse():
                # Yield event with all fields preserved
                yield {
                    "event": sse.event,
                    "data": sse.data,
                    "id": sse.id,
                    "retry": sse.retry,
                }
    
    async def forward_get_check(
        self,
        url: str,
        headers: Dict[str, str],
    ) -> httpx.Response:
        """
        Check if upstream supports GET SSE (optional per MCP spec).
        
        Args:
            url: Upstream MCP endpoint URL
            headers: Request headers to forward
        
        Returns:
            Raw httpx Response object (without raising on 4xx/5xx)
        """
        client = self._get_client()
        
        logger.debug(f"Checking GET SSE support at {url}")
        
        # Don't raise on 4xx/5xx - let caller handle status code
        response = await client.get(url, headers=headers, follow_redirects=True)
        
        return response

    
    async def forward_delete(
        self,
        url: str,
        headers: Dict[str, str],
    ) -> httpx.Response:
        """
        Forward a DELETE request to upstream MCP server.
        
        Args:
            url: Upstream MCP endpoint URL
            headers: Request headers to forward
        
        Returns:
            Raw httpx Response object
        """
        client = self._get_client()
        
        logger.debug(f"Forwarding DELETE to {url}")
        
        response = await client.delete(url, headers=headers)
        
        return response
