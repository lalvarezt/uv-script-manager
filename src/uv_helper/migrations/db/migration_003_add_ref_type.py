"""Migration #3: Add ref_type field to existing scripts."""

from rich.console import Console
from tinydb import TinyDB

from ...constants import DB_TABLE_SCRIPTS
from ...refs import infer_ref_type as infer_shared_ref_type
from .base import Migration

console = Console()


class Migration003AddRefType(Migration):
    """Migration #3: Add ref_type field to existing scripts.

    This migration adds the ref_type field to track whether a script was
    installed from a branch, tag, or commit. Existing scripts have their
    ref_type inferred from the ref value.
    """

    version = 3

    def description(self) -> str:
        """Return migration description."""
        return "Add ref_type field to existing scripts"

    def migrate(self, db: TinyDB) -> None:
        """Add ref_type field to all existing scripts."""
        scripts_table = db.table(DB_TABLE_SCRIPTS)

        updated_count = 0
        for doc in scripts_table.all():
            if "ref_type" not in doc:
                ref = doc.get("ref")
                ref_type = infer_shared_ref_type(ref)
                scripts_table.update({"ref_type": ref_type}, doc_ids=[doc.doc_id])
                updated_count += 1

        if updated_count > 0:
            console.print(f"  Migrated {updated_count} script(s) to include ref_type field")
