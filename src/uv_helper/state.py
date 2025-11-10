"""State management for UV-Helper."""

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field
from tinydb import Query, TinyDB

from .constants import DB_TABLE_SCRIPTS, SourceType
from .migrations import MIGRATIONS, MigrationRunner
from .utils import ensure_dir


class ScriptInfo(BaseModel):
    """Information about an installed script.

    Pydantic model that automatically handles serialization/deserialization,
    validation, and type coercion for script metadata.

    Supports both Git and local sources via the source_type field.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    source_type: SourceType
    installed_at: datetime
    repo_path: Path
    symlink_path: Path | None = None
    dependencies: list[str] = Field(default_factory=list)
    # Git-specific fields (required when source_type=SourceType.GIT)
    source_url: str | None = None
    ref: str | None = None
    commit_hash: str | None = None
    # Local-specific fields
    source_path: Path | None = None  # Original source path for updates
    copy_parent_dir: bool = False  # Whether entire parent directory was copied


class StateManager:
    """Manages state using TinyDB for automatic atomic updates and query support."""

    def __init__(self, state_file: Path):
        """
        Initialize state manager with TinyDB.

        Automatically runs any pending database migrations.

        Args:
            state_file: Path to state file
        """
        self.state_file = state_file
        ensure_dir(state_file.parent)

        self.db = TinyDB(state_file)
        self.scripts = self.db.table(DB_TABLE_SCRIPTS)

        # Run any pending migrations
        runner = MigrationRunner(self.db, state_file)
        if runner.needs_migration():
            runner.run_migrations(MIGRATIONS)

    def add_script(self, script: ScriptInfo) -> None:
        """Add or update script in database."""
        data = script.model_dump(mode="json")
        Script = Query()
        self.scripts.upsert(data, Script.name == script.name)

    def remove_script(self, name: str) -> None:
        """Remove script from database."""
        Script = Query()
        self.scripts.remove(Script.name == name)

    def get_script(self, name: str) -> ScriptInfo | None:
        """Get script by name."""
        Script = Query()
        result = self.scripts.get(Script.name == name)
        return ScriptInfo.model_validate(result) if result else None

    def has_script(self, name: str) -> bool:
        """
        Check if script is installed.

        Args:
            name: Script name

        Returns:
            True if script is installed
        """
        return self.get_script(name) is not None

    def list_scripts(self) -> list[ScriptInfo]:
        """List all installed scripts."""
        results = self.scripts.all()
        return [ScriptInfo.model_validate(r) for r in results]

    def get_scripts_from_repo(self, repo_path: Path) -> list[ScriptInfo]:
        """
        Get all scripts from a specific repository.

        Args:
            repo_path: Repository path

        Returns:
            List of ScriptInfo from that repository
        """
        Script = Query()
        results = self.scripts.search(Script.repo_path == str(repo_path))
        return [ScriptInfo.model_validate(r) for r in results]

    def get_script_by_symlink(self, symlink_name: str) -> ScriptInfo | None:
        """
        Get script by its symlink name (alias).

        Args:
            symlink_name: Name of the symlink (without path)

        Returns:
            ScriptInfo if found, None otherwise
        """
        # Search through all scripts and match by symlink name
        all_scripts = self.list_scripts()
        for script in all_scripts:
            if script.symlink_path and script.symlink_path.name == symlink_name:
                return script
        return None
