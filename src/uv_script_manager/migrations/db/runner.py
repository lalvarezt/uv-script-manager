"""Migration runner for database schema updates."""

import shutil
from datetime import datetime
from pathlib import Path

from rich.console import Console
from tinydb import TinyDB

from ...constants import DB_METADATA_DOC_ID, DB_TABLE_METADATA, METADATA_KEY_SCHEMA_VERSION
from .base import CURRENT_SCHEMA_VERSION, Migration

console = Console()


class MigrationRunner:
    """Runs database migrations."""

    def __init__(self, db: TinyDB, db_path: Path) -> None:
        """
        Initialize migration runner.

        Args:
            db: TinyDB database instance
            db_path: Path to the database file (for backup purposes)
        """
        self.db = db
        self.db_path = db_path
        # Metadata table stores schema version as a single document with doc_id=1.
        # Using a fixed doc_id ensures we always retrieve/update the same document
        # instead of creating multiple version entries.
        self.metadata = db.table(DB_TABLE_METADATA)

    def get_schema_version(self) -> int:
        """
        Get current schema version from database.

        Returns:
            Current schema version, or 0 if not set
        """
        result = self.metadata.get(doc_id=DB_METADATA_DOC_ID)
        if result and isinstance(result, dict):
            return result.get(METADATA_KEY_SCHEMA_VERSION, 0)
        return 0

    def get_applied_migrations(self) -> dict[int, str]:
        """
        Get mapping of applied migration versions to their checksums.

        Returns:
            Dict mapping version number to checksum
        """
        doc = self.metadata.get(doc_id=DB_METADATA_DOC_ID)
        if not doc or isinstance(doc, list):
            return {}

        # New format: {'migrations': {1: 'checksum1', 2: 'checksum2'}}
        migrations_data = doc.get("migrations", {})
        # Convert string keys back to ints
        return {int(k): v for k, v in migrations_data.items()}

    def mark_migration_applied(self, migration: Migration) -> None:
        """
        Mark a migration as applied with its checksum.

        Args:
            migration: Applied migration
        """
        applied = self.get_applied_migrations()
        applied[migration.version] = migration.checksum

        # Convert int keys to strings for JSON storage
        applied_str_keys = {str(k): v for k, v in applied.items()}

        # Use update if doc exists, otherwise insert
        if self.metadata.get(doc_id=DB_METADATA_DOC_ID):
            self.metadata.update(
                {METADATA_KEY_SCHEMA_VERSION: migration.version, "migrations": applied_str_keys},
                doc_ids=[DB_METADATA_DOC_ID],
            )
        else:
            self.metadata.insert(
                {METADATA_KEY_SCHEMA_VERSION: migration.version, "migrations": applied_str_keys}
            )

    def needs_migration(self) -> bool:
        """
        Check if any migrations need to be run.

        Returns:
            True if migrations are pending
        """
        current_version = self.get_schema_version()
        return current_version < CURRENT_SCHEMA_VERSION

    def backup_database(self) -> Path | None:
        """
        Create a backup of the database file before migrations.

        Returns:
            Path to backup file, or None if backup failed
        """
        try:
            # Create backup filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = self.db_path.parent / f"{self.db_path.stem}_backup_{timestamp}{self.db_path.suffix}"

            # Create backup
            shutil.copy2(self.db_path, backup_path)
            console.print(f"  Created backup: {backup_path}")
            return backup_path
        except Exception as e:
            console.print(f"[yellow]Warning:[/yellow] Failed to create backup: {e}")
            return None

    def verify_migrations(self, migrations: list[Migration]) -> list[str]:
        """
        Verify that applied migrations haven't been modified.

        Args:
            migrations: List of migration instances

        Returns:
            List of verification errors (empty if all valid)
        """
        errors = []
        applied = self.get_applied_migrations()

        for migration in migrations:
            if migration.version in applied:
                stored_checksum = applied[migration.version]
                if not migration.verify_checksum(stored_checksum):
                    errors.append(
                        f"Migration {migration.version} has been modified!\n"
                        f"  Expected: {stored_checksum}\n"
                        f"  Actual: {migration.checksum}\n"
                        f"  This may indicate database corruption."
                    )

        return errors

    def run_migrations(self, migrations: list[Migration]) -> None:
        """
        Run all pending migrations with verification and automatic backup.

        Creates a backup of the database before applying migrations.
        Verifies that previously applied migrations haven't been modified.
        If a migration fails, the backup can be manually restored.

        Args:
            migrations: List of migrations to run

        Raises:
            RuntimeError: If migration verification fails
        """
        # Verify existing migrations first
        errors = self.verify_migrations(migrations)
        if errors:
            error_msg = "\n".join(errors)
            raise RuntimeError(f"Migration verification failed:\n{error_msg}")

        current_version = self.get_schema_version()

        if current_version >= CURRENT_SCHEMA_VERSION:
            # Already at latest version
            return

        console.print(f"Running database migrations (v{current_version} -> v{CURRENT_SCHEMA_VERSION})...")

        # Create backup before migrations
        backup_path = self.backup_database()

        # Run each migration that hasn't been applied yet
        for migration in migrations:
            if migration.version > current_version:
                try:
                    console.print(
                        f"  Applying migration {migration.version}: {migration.description()} "
                        f"(checksum: {migration.checksum})"
                    )
                    migration.migrate(self.db)
                    self.mark_migration_applied(migration)
                except Exception as e:
                    console.print(f"[red]Error:[/red] Migration {migration.version} failed: {e}")
                    if backup_path:
                        console.print(f"[yellow]Hint:[/yellow] Restore backup from: {backup_path}")
                    raise

        console.print("Database migrations completed.")
