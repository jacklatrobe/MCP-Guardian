"""JSON diff utilities for comparing snapshots."""
import json
from typing import Any, Dict, Optional


def json_diff(old: str, new: str) -> Dict[str, Any]:
    """
    Create a simple diff between two JSON strings.
    
    Args:
        old: Old JSON string
        new: New JSON string
    
    Returns:
        Dictionary with diff information
    """
    try:
        old_data = json.loads(old)
        new_data = json.loads(new)
    except json.JSONDecodeError as e:
        return {"error": f"Failed to parse JSON: {e}"}
    
    diff = {
        "changed": old != new,
        "old_keys": set(flatten_keys(old_data)),
        "new_keys": set(flatten_keys(new_data)),
    }
    
    # Calculate additions and removals
    diff["added_keys"] = list(diff["new_keys"] - diff["old_keys"])
    diff["removed_keys"] = list(diff["old_keys"] - diff["new_keys"])
    
    # Convert sets to lists for JSON serialization
    diff["old_keys"] = list(diff["old_keys"])
    diff["new_keys"] = list(diff["new_keys"])
    
    # Add detailed comparison for major sections
    diff["tools_changed"] = compare_list_section(
        old_data.get("tools", []),
        new_data.get("tools", []),
        "name"
    )
    diff["resources_changed"] = compare_list_section(
        old_data.get("resources", []),
        new_data.get("resources", []),
        "uri"
    )
    diff["prompts_changed"] = compare_list_section(
        old_data.get("prompts", []),
        new_data.get("prompts", []),
        "name"
    )
    
    return diff


def flatten_keys(data: Any, prefix: str = "") -> list[str]:
    """
    Flatten nested dictionary keys into dot-notation paths.
    
    Args:
        data: Data to flatten
        prefix: Current key prefix
    
    Returns:
        List of flattened key paths
    """
    keys = []
    
    if isinstance(data, dict):
        for key, value in data.items():
            new_prefix = f"{prefix}.{key}" if prefix else key
            if isinstance(value, (dict, list)):
                keys.extend(flatten_keys(value, new_prefix))
            else:
                keys.append(new_prefix)
    elif isinstance(data, list):
        for i, item in enumerate(data):
            new_prefix = f"{prefix}[{i}]"
            if isinstance(item, (dict, list)):
                keys.extend(flatten_keys(item, new_prefix))
            else:
                keys.append(new_prefix)
    
    return keys


def compare_list_section(old_list: list, new_list: list, key_field: str) -> Dict[str, Any]:
    """
    Compare two lists of items (tools, resources, prompts).
    
    Args:
        old_list: Old list of items
        new_list: New list of items
        key_field: Field to use as unique key (e.g., "name", "uri")
    
    Returns:
        Dictionary with added/removed/modified items
    """
    old_keys = {item.get(key_field) for item in old_list if key_field in item}
    new_keys = {item.get(key_field) for item in new_list if key_field in item}
    
    return {
        "added": list(new_keys - old_keys),
        "removed": list(old_keys - new_keys),
        "common": list(old_keys & new_keys),
        "count_old": len(old_list),
        "count_new": len(new_list),
    }


def create_human_readable_diff(old: str, new: str) -> str:
    """
    Create a human-readable diff summary.
    
    Args:
        old: Old JSON string
        new: New JSON string
    
    Returns:
        Human-readable diff string
    """
    diff = json_diff(old, new)
    
    if "error" in diff:
        return f"Error: {diff['error']}"
    
    if not diff["changed"]:
        return "No changes detected."
    
    lines = ["Changes detected:"]
    
    # Tools
    if diff["tools_changed"]["added"] or diff["tools_changed"]["removed"]:
        lines.append("\nTools:")
        if diff["tools_changed"]["added"]:
            lines.append(f"  + Added: {', '.join(diff['tools_changed']['added'])}")
        if diff["tools_changed"]["removed"]:
            lines.append(f"  - Removed: {', '.join(diff['tools_changed']['removed'])}")
    
    # Resources
    if diff["resources_changed"]["added"] or diff["resources_changed"]["removed"]:
        lines.append("\nResources:")
        if diff["resources_changed"]["added"]:
            lines.append(f"  + Added: {', '.join(diff['resources_changed']['added'])}")
        if diff["resources_changed"]["removed"]:
            lines.append(f"  - Removed: {', '.join(diff['resources_changed']['removed'])}")
    
    # Prompts
    if diff["prompts_changed"]["added"] or diff["prompts_changed"]["removed"]:
        lines.append("\nPrompts:")
        if diff["prompts_changed"]["added"]:
            lines.append(f"  + Added: {', '.join(diff['prompts_changed']['added'])}")
        if diff["prompts_changed"]["removed"]:
            lines.append(f"  - Removed: {', '.join(diff['prompts_changed']['removed'])}")
    
    return "\n".join(lines)
