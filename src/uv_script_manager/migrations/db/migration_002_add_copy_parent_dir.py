"""Migration #2: Add copy_parent_dir field to existing scripts."""

from rich.console import Console
from tinydb import TinyDB

from ...constants import DB_TABLE_SCRIPTS
from .base import Migration

console = Console()


class Migration002AddCopyParentDir(Migration):
    """Migration #2: Add copy_parent_dir field to existing scripts.

    This migration adds the copy_parent_dir field to track whether a local
    script was installed with the --copy-parent-dir flag. Existing scripts
    default to False (individual file copy mode).
    """

    version = 2

    def description(self) -> str:
        """Return migration description."""
        return "Add copy_parent_dir field to existing scripts"

    def migrate(self, db: TinyDB) -> None:
        """Add copy_parent_dir field to all existing scripts."""
        scripts_table = db.table(DB_TABLE_SCRIPTS)

        # Update all scripts that don't have copy_parent_dir
        updated_count = 0
        for doc in scripts_table.all():
            if "copy_parent_dir" not in doc:
                scripts_table.update({"copy_parent_dir": False}, doc_ids=[doc.doc_id])
                updated_count += 1

        if updated_count > 0:
            console.print(f"  Migrated {updated_count} script(s) to include copy_parent_dir field")
