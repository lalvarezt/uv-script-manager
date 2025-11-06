"""Update command handlers for UV-Helper."""

import shutil
from datetime import datetime

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from ..config import Config
from ..constants import SourceType
from ..git_manager import (
    GitError,
    clone_or_update,
    get_current_commit_hash,
    get_default_branch,
    verify_git_available,
)
from ..script_installer import ScriptInstallerError, install_script
from ..state import ScriptInfo, StateManager


class UpdateHandler:
    """Handles script update logic."""

    def __init__(self, config: Config, console: Console):
        """
        Initialize update handler.

        Args:
            config: Application configuration
            console: Rich console for output
        """
        self.config = config
        self.console = console
        self.state_manager = StateManager(config.state_file)

    def update(self, script_name: str, force: bool, exact: bool | None) -> tuple[str, str]:
        """
        Update a single script.

        Args:
            script_name: Name of script to update
            force: Force reinstall even if up-to-date
            exact: Use --exact flag in shebang

        Returns:
            Tuple of (script_name, status)
        """
        # Check if script exists
        script_info = self.state_manager.get_script(script_name)
        if not script_info:
            self.console.print(f"[red]Error:[/red] Script '{script_name}' not found.")
            raise ValueError(f"Script '{script_name}' not found")

        # Branch based on source type
        if script_info.source_type == SourceType.LOCAL:
            return self._update_local_script(script_info, script_name, exact)
        else:
            return self._update_git_script(script_info, script_name, force, exact)

    def update_all(self, force: bool, exact: bool | None) -> list[tuple[str, str]]:
        """
        Update all installed scripts.

        Args:
            force: Force reinstall all scripts
            exact: Use --exact flag in shebang

        Returns:
            List of (script_name, status) tuples
        """
        scripts = self.state_manager.list_scripts()

        if not scripts:
            self.console.print("No scripts installed.")
            return []

        self.console.print(f"Updating {len(scripts)} script(s)...")

        results = []
        git_checked = False

        for script_info in scripts:
            # Skip local scripts (they need manual source updates)
            if script_info.source_type == SourceType.LOCAL:
                results.append((script_info.name, "skipped (local)"))
                continue

            # Verify git available once
            if not git_checked:
                try:
                    verify_git_available()
                except GitError as e:
                    self.console.print(f"[red]Error:[/red] Git: {e}")
                    raise
                git_checked = True

            try:
                status = self._update_git_script_internal(script_info, force, exact)
                results.append((script_info.name, status))
            except (GitError, ScriptInstallerError) as e:
                results.append((script_info.name, f"Error: {e}"))

        return results

    def _update_local_script(
        self, script_info: ScriptInfo, script_name: str, exact: bool | None
    ) -> tuple[str, str]:
        """Update a local script."""
        if not script_info.source_path or not script_info.source_path.exists():
            self.console.print(
                f"[red]Error:[/red] Source directory not found: {script_info.source_path}"
            )
            self.console.print("The original source directory may have been moved or deleted.")
            raise FileNotFoundError(f"Source directory not found: {script_info.source_path}")

        try:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=self.console,
                transient=True,
            ) as progress:
                task = progress.add_task("Updating from source...", total=None)

                # Re-copy from source directory
                if script_info.copy_parent_dir:
                    # Copy entire directory contents
                    for item in script_info.source_path.iterdir():
                        dest = script_info.repo_path / item.name
                        if item.is_dir():
                            if dest.exists():
                                shutil.rmtree(dest)
                            shutil.copytree(item, dest)
                        else:
                            shutil.copy2(item, dest)
                else:
                    # Copy just the script file
                    source_script = script_info.source_path / script_name
                    dest_script = script_info.repo_path / script_name
                    dest_script.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source_script, dest_script)

                progress.update(task, completed=True)

            # Reinstall script
            script_path = script_info.repo_path / script_name
            symlink_path = install_script(
                script_path,
                script_info.dependencies,
                self.config.install_dir,
                auto_chmod=self.config.auto_chmod,
                auto_symlink=self.config.auto_symlink,
                verify_after_install=self.config.verify_after_install,
                use_exact=exact if exact is not None else self.config.use_exact_flag,
            )

            # Update state
            script_info.installed_at = datetime.now()
            script_info.symlink_path = symlink_path
            self.state_manager.add_script(script_info)

            return (script_name, "updated")

        except (ScriptInstallerError, Exception) as e:
            return (script_name, f"Error: {e}")

    def _update_git_script(
        self, script_info: ScriptInfo, script_name: str, force: bool, exact: bool | None
    ) -> tuple[str, str]:
        """Update a Git script."""
        assert script_info.source_url is not None
        assert script_info.ref is not None

        try:
            verify_git_available()
        except GitError as e:
            self.console.print(f"[red]Error:[/red] Git: {e}")
            raise

        try:
            status = self._update_git_script_internal(script_info, force, exact)
            return (script_name, status)
        except (GitError, ScriptInstallerError) as e:
            return (script_name, f"Error: {e}")

    def _update_git_script_internal(
        self, script_info: ScriptInfo, force: bool, exact: bool | None
    ) -> str:
        """Internal method to update a Git script."""
        assert script_info.source_url is not None
        assert script_info.ref is not None

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=self.console,
            transient=True,
        ) as progress:
            task = progress.add_task("Updating repository...", total=None)

            clone_or_update(
                script_info.source_url,
                script_info.ref,
                script_info.repo_path,
                depth=self.config.clone_depth,
            )

            progress.update(task, completed=True)

        # Check if there are updates
        new_commit_hash = get_current_commit_hash(script_info.repo_path)

        # Get the actual current branch
        try:
            actual_branch = get_default_branch(script_info.repo_path)
        except GitError:
            actual_branch = script_info.ref

        if new_commit_hash == script_info.commit_hash and not force:
            # Still update the ref in state if it changed
            if actual_branch != script_info.ref:
                script_info.ref = actual_branch
                self.state_manager.add_script(script_info)
            return "up-to-date"

        # Reinstall script
        script_path = script_info.repo_path / script_info.name
        symlink_path = install_script(
            script_path,
            script_info.dependencies,
            self.config.install_dir,
            auto_chmod=self.config.auto_chmod,
            auto_symlink=self.config.auto_symlink,
            verify_after_install=self.config.verify_after_install,
            use_exact=exact if exact is not None else self.config.use_exact_flag,
        )

        # Update state with new commit hash and actual branch
        script_info.commit_hash = new_commit_hash
        script_info.ref = actual_branch
        script_info.installed_at = datetime.now()
        script_info.symlink_path = symlink_path
        self.state_manager.add_script(script_info)

        return "updated"
