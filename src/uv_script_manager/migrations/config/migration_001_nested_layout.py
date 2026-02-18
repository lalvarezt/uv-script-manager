"""Config migration #1: move legacy sections into nested layout."""

from typing import Any

from .utils import merge_config_data


def migration_001_nested_layout(data: dict[str, Any]) -> dict[str, Any]:
    """Move legacy top-level config sections into nested layout."""
    migrated = dict(data)

    legacy_paths = migrated.pop("paths", None)
    legacy_git = migrated.pop("git", None)
    legacy_install = migrated.pop("install", None)

    legacy_mapped: dict[str, Any] = {}

    if isinstance(legacy_paths, dict):
        legacy_mapped.setdefault("global", {}).setdefault("paths", {}).update(legacy_paths)

    if isinstance(legacy_git, dict):
        legacy_mapped.setdefault("global", {}).setdefault("git", {}).update(legacy_git)

    if isinstance(legacy_install, dict):
        legacy_mapped.setdefault("global", {}).setdefault("install", {}).update(legacy_install)

    return merge_config_data(legacy_mapped, migrated)
