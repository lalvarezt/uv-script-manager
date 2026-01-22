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
    ref_type: str | None = None  # "branch", "tag", "commit", or "default"
    commit_hash: str | None = None
    # Local-specific fields
    source_path: Path | None = None  # Original source path for updates
    copy_parent_dir: bool = False  # Whether entire parent directory was copied

    @property
    def display_name(self) -> str:
        """Get display name (symlink name if exists, otherwise script name)."""
        return self.symlink_path.name if self.symlink_path else self.name


class StateManager:
    """Manages state using TinyDB for automatic atomic updates and query support."""

    def __init__(self, state_file: Path) -> None:
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

    def get_script_flexible(self, name: str) -> ScriptInfo | None:
        """
        Get script by name or symlink name.

        Tries to find script first by name, then by symlink name (alias).

        Args:
            name: Script name or symlink name

        Returns:
            ScriptInfo if found, None otherwise
        """
        # Try by name first
        script = self.get_script(name)
        if script:
            return script
        # Try by symlink
        return self.get_script_by_symlink(name)

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
        # Use TinyDB query with custom test for better performance
        Script = Query()
        results = self.scripts.search(
            Script.symlink_path.test(lambda path: path is not None and Path(path).name == symlink_name)
        )
        return ScriptInfo.model_validate(results[0]) if results else None

    def validate_state(self) -> list[str]:
        """
        Validate state integrity.

        Checks:
        - Symlinks exist and point to valid targets
        - Script files exist in repo_path
        - Repo paths exist
        - Source paths exist for local scripts

        Returns:
            List of validation issues (empty if valid)
        """
        issues = []
        scripts = self.list_scripts()

        for script in scripts:
            # Check symlink validity
            if script.symlink_path:
                if not script.symlink_path.exists():
                    issues.append(f"Broken symlink for '{script.name}': {script.symlink_path}")
                elif not script.symlink_path.is_symlink():
                    issues.append(f"Expected symlink but found file: {script.symlink_path}")
                else:
                    try:
                        target = script.symlink_path.resolve()
                        expected = script.repo_path / script.name
                        if target != expected:
                            issues.append(
                                f"Symlink points to wrong target for '{script.name}': {target} != {expected}"
                            )
                    except (OSError, RuntimeError):
                        issues.append(f"Cannot resolve symlink for '{script.name}': {script.symlink_path}")

            # Check script file exists
            script_file = script.repo_path / script.name
            if not script_file.exists():
                issues.append(f"Script file missing for '{script.name}': {script_file}")

            # Check repo path exists
            if not script.repo_path.exists():
                issues.append(f"Repository directory missing for '{script.name}': {script.repo_path}")

            # Check source_path for local scripts
            if script.source_type == SourceType.LOCAL and script.source_path:
                if not script.source_path.exists():
                    issues.append(
                        f"Source directory missing for local script '{script.name}': {script.source_path}"
                    )

        return issues

    def repair_state(self, auto_fix: bool = False) -> dict[str, int]:
        """
        Repair state inconsistencies.

        Args:
            auto_fix: If True, automatically fix issues. If False, return report only.

        Returns:
            Dict with counts: {
                'broken_symlinks_removed': int,
                'missing_scripts_removed': int,
            }
        """
        report = {"broken_symlinks_removed": 0, "missing_scripts_removed": 0}

        scripts = self.list_scripts()
        to_remove = []

        for script in scripts:
            # Remove scripts with missing files
            script_file = script.repo_path / script.name
            if not script_file.exists() and not script.repo_path.exists():
                to_remove.append(script.name)
                report["missing_scripts_removed"] += 1

            # Remove broken symlinks
            elif script.symlink_path and not script.symlink_path.exists():
                if auto_fix:
                    try:
                        script.symlink_path.unlink(missing_ok=True)
                    except OSError:
                        pass
                report["broken_symlinks_removed"] += 1

        # Remove invalid scripts from state
        if auto_fix:
            for name in to_remove:
                self.remove_script(name)

        return report
