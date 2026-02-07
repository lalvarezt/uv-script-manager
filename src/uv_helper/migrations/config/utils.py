"""Shared utilities for config migrations."""

from typing import Any


def merge_config_data(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Merge config dictionaries recursively."""
    merged = dict(base)
    for key, value in override.items():
        base_value = merged.get(key)
        if isinstance(base_value, dict) and isinstance(value, dict):
            merged[key] = merge_config_data(base_value, value)
        else:
            merged[key] = value
    return merged
