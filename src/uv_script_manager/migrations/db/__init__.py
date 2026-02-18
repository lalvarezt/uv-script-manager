"""Database migration system for state."""

from .base import CURRENT_SCHEMA_VERSION, Migration
from .migration_001_add_source_type import Migration001AddSourceType
from .migration_002_add_copy_parent_dir import Migration002AddCopyParentDir
from .migration_003_add_ref_type import Migration003AddRefType
from .runner import MigrationRunner

MIGRATIONS: list[Migration] = [
    Migration001AddSourceType(),
    Migration002AddCopyParentDir(),
    Migration003AddRefType(),
]

__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "Migration",
    "Migration001AddSourceType",
    "Migration002AddCopyParentDir",
    "Migration003AddRefType",
    "MigrationRunner",
    "MIGRATIONS",
]
