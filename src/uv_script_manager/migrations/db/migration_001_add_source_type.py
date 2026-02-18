"""Migration #1: Add source_type field to existing scripts."""

from rich.console import Console
from tinydb import TinyDB

from ...constants import DB_TABLE_SCRIPTS, SourceType
from .base import Migration

console = Console()


class Migration001AddSourceType(Migration):
    """Migration #1: Add source_type field to existing scripts.

    Before this migration, all scripts were from Git repositories.
    This migration adds the source_type field and sets it to "git"
    for all existing scripts.
    """

    version = 1

    def description(self) -> str:
        """Return migration description."""
        return "Add source_type field to existing scripts"

    def migrate(self, db: TinyDB) -> None:
        """Add source_type field to all existing scripts."""
        scripts_table = db.table(DB_TABLE_SCRIPTS)

        # Update all scripts that don't have source_type
        updated_count = 0
        for doc in scripts_table.all():
            if "source_type" not in doc:
                scripts_table.update({"source_type": SourceType.GIT.value}, doc_ids=[doc.doc_id])
                updated_count += 1

        if updated_count > 0:
            console.print(f"  Migrated {updated_count} script(s) to include source_type field")
