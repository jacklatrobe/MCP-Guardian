"""Security dependencies for admin routes."""
import logging
import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from .config import settings

logger = logging.getLogger(__name__)

# HTTPBasic with realm for proper browser handling
security = HTTPBasic(realm="MCP Guardian Admin")


def get_current_admin(
    credentials: Annotated[HTTPBasicCredentials, Depends(security)]
) -> str:
    """
    Validate HTTP Basic Auth credentials for admin access.
    
    Returns the username if authentication succeeds.
    Raises HTTPException if authentication fails.
    """
    # Username can be anything (we only check password)
    # Use constant-time comparison to prevent timing attacks
    is_password_correct = secrets.compare_digest(
        credentials.password.encode("utf-8"),
        settings.admin_password.encode("utf-8")
    )
    
    if not is_password_correct:
        logger.warning(f"Failed admin login attempt for user: {credentials.username}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": 'Basic realm="MCP Guardian Admin"'},
        )
    
    logger.debug(f"Successful admin login: {credentials.username}")
    return credentials.username
