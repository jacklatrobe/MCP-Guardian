"""RFC 8785 JCS canonicalization and hashing utilities."""
import hashlib
import json
from typing import Any, Dict

import jcs


def remove_volatile_fields(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Remove fields known to fluctuate that shouldn't affect fingerprinting.
    
    This is a placeholder - adjust based on actual MCP response structures.
    Examples: timestamps, request IDs, dynamic metadata.
    """
    # For now, we'll keep all fields as the PRD suggests capturing full surface
    # Future enhancement: filter out known volatile fields per MCP spec
    return data


def sort_by_stable_key(items: list, key_field: str = "name") -> list:
    """
    Sort a list of items by a stable key field.
    
    Args:
        items: List of dictionaries to sort
        key_field: Field name to sort by (default: "name")
    
    Returns:
        Sorted list
    """
    if not items:
        return items
    
    # Handle both dict and nested structures
    try:
        return sorted(items, key=lambda x: x.get(key_field, ""))
    except (KeyError, TypeError):
        # If sorting fails, return as-is (better than crashing)
        return items


def create_fingerprint(
    tools: list,
    resources: list,
    resource_templates: list,
    prompts: list,
) -> Dict[str, Any]:
    """
    Create a deterministic fingerprint structure from MCP lists.
    
    Args:
        tools: List of tools from tools/list
        resources: List of resources from resources/list
        resource_templates: List of resource templates from resources/templates/list
        prompts: List of prompts from prompts/list
    
    Returns:
        Deterministic structure ready for canonicalization
    """
    # Sort each list by stable keys
    sorted_tools = sort_by_stable_key(tools, "name")
    sorted_resources = sort_by_stable_key(resources, "uri")
    sorted_resource_templates = sort_by_stable_key(resource_templates, "uriTemplate")
    sorted_prompts = sort_by_stable_key(prompts, "name")
    
    fingerprint = {
        "tools": sorted_tools,
        "resources": sorted_resources,
        "resource_templates": sorted_resource_templates,
        "prompts": sorted_prompts,
    }
    
    return fingerprint


def canonicalize_json(data: Dict[str, Any]) -> str:
    """
    Canonicalize JSON according to RFC 8785 JCS.
    
    Args:
        data: Dictionary to canonicalize
    
    Returns:
        Canonical JSON string
    """
    # Use jcs library for RFC 8785 compliance
    canonical_bytes = jcs.canonicalize(data)
    return canonical_bytes.decode("utf-8")


def hash_canonical_json(canonical_json: str) -> str:
    """
    Create SHA-256 hash of canonical JSON.
    
    Args:
        canonical_json: Canonical JSON string
    
    Returns:
        Hex-encoded SHA-256 hash
    """
    hash_obj = hashlib.sha256(canonical_json.encode("utf-8"))
    return hash_obj.hexdigest()


def create_snapshot_hash(
    tools: list,
    resources: list,
    resource_templates: list,
    prompts: list,
) -> tuple[str, str]:
    """
    Create a complete snapshot hash from MCP capability lists.
    
    Args:
        tools: List of tools
        resources: List of resources
        resource_templates: List of resource templates
        prompts: List of prompts
    
    Returns:
        Tuple of (canonical_json_string, hash_hex)
    """
    # Create deterministic fingerprint
    fingerprint = create_fingerprint(tools, resources, resource_templates, prompts)
    
    # Canonicalize
    canonical = canonicalize_json(fingerprint)
    
    # Hash
    hash_hex = hash_canonical_json(canonical)
    
    return canonical, hash_hex
