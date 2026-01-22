"""Base classes for database migrations."""

import hashlib
import inspect
from abc import ABC, abstractmethod

from tinydb import TinyDB

# Current schema version - increment when adding new migrations.
# This should match the highest version number in the MIGRATIONS list.
CURRENT_SCHEMA_VERSION = 3


class Migration(ABC):
    """
    Base class for database migrations with integrity verification.

    Each migration has a version number, description, and checksum.
    The checksum prevents corruption by verifying migration code hasn't changed
    after being applied to a database.
    """

    version: int

    @abstractmethod
    def migrate(self, db: TinyDB) -> None:
        """
        Perform the migration on the database.

        Args:
            db: TinyDB database instance
        """
        pass

    @abstractmethod
    def description(self) -> str:
        """Return a human-readable description of this migration."""
        pass

    @property
    def checksum(self) -> str:
        """
        Calculate checksum of the migration logic.

        Uses SHA256 hash of the migrate() method source code.
        This ensures migration code hasn't been modified after being applied.

        Returns:
            Hex string of SHA256 hash (first 16 chars)
        """
        # Get source code of migrate() method
        source = inspect.getsource(self.migrate)
        # Normalize whitespace to prevent formatting changes from affecting checksum
        normalized = " ".join(source.split())
        # Calculate SHA256
        return hashlib.sha256(normalized.encode()).hexdigest()[:16]

    def verify_checksum(self, stored_checksum: str) -> bool:
        """
        Verify that migration hasn't been modified.

        Args:
            stored_checksum: Previously calculated checksum

        Returns:
            True if checksums match
        """
        return self.checksum == stored_checksum
