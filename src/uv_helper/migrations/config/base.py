"""Configuration file migrations."""

from typing import Any, Callable

from .migration_001_nested_layout import migration_001_nested_layout

MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {
    1: migration_001_nested_layout,
}

CURRENT_SCHEMA_VERSION = 1
