"""Runner for config schema migrations."""

from typing import Any

from .base import CURRENT_SCHEMA_VERSION, MIGRATIONS


def get_schema_version(data: dict[str, Any]) -> int:
    """Get config schema version from metadata section."""
    meta = data.get("meta")
    if not isinstance(meta, dict):
        return 0

    version = meta.get("schema_version", 0)
    if isinstance(version, int) and version >= 0:
        return version

    return 0


def set_schema_version(data: dict[str, Any], version: int) -> None:
    """Set config schema version in metadata section."""
    meta = data.get("meta")
    if not isinstance(meta, dict):
        meta = {}
        data["meta"] = meta
    meta["schema_version"] = version


def run_migrations(data: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Run pending config migrations based on schema version."""
    current_version = get_schema_version(data)
    if current_version >= CURRENT_SCHEMA_VERSION:
        return data, False

    migrated = dict(data)
    for version in range(current_version + 1, CURRENT_SCHEMA_VERSION + 1):
        migration = MIGRATIONS.get(version)
        if migration is not None:
            migrated = migration(migrated)
        set_schema_version(migrated, version)

    return migrated, True
