"""Config migration system for UV-Helper configuration files."""

from .base import CURRENT_SCHEMA_VERSION, MIGRATIONS
from .migration_001_nested_layout import migration_001_nested_layout
from .runner import run_migrations
from .utils import merge_config_data

__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "MIGRATIONS",
    "migration_001_nested_layout",
    "run_migrations",
    "merge_config_data",
]
