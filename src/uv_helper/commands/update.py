"""Update command handlers for UV-Helper."""

from datetime import datetime

from rich.console import Console

from ..config import Config
from ..constants import SourceType
from ..deps import resolve_dependencies
from ..git_manager import (
    GitError,
    clone_or_update,
    get_current_commit_hash,
    get_default_branch,
    verify_git_available,
)
from ..script_installer import InstallConfig, ScriptInstallerError, install_script
from ..state import ScriptInfo, StateManager
from ..utils import copy_directory_contents, handle_git_error, progress_spinner


class UpdateHandler:
    """Handles script update logic."""

    def __init__(self, config: Config, console: Console) -> None:
        """
        Initialize update handler.

        Args:
            config: Application configuration
            console: Rich console for output
        """
        self.config = config
        self.console = console
        self.state_manager = StateManager(config.state_file)

    def update(
        self, script_name: str, force: bool, exact: bool | None, refresh_deps: bool = False
    ) -> tuple[str, str]:
        """
        Update a single script.

        Args:
            script_name: Name of script to update (can be original name or alias)
            force: Force reinstall even if up-to-date
            exact: Use --exact flag in shebang
            refresh_deps: Re-resolve dependencies from repository

        Returns:
            Tuple of (script_name, status)
        """
        # Check if script exists - try by original name or symlink name
        script_info = self.state_manager.get_script_flexible(script_name)
        if not script_info:
            self.console.print(f"[red]Error:[/red] Script '{script_name}' not found.")
            raise ValueError(f"Script '{script_name}' not found")

        display_name = script_info.display_name

        # Branch based on source type (use actual script name from state, not user input)
        if script_info.source_type == SourceType.LOCAL:
            return self._update_local_script(script_info, script_info.name, exact, refresh_deps)
        else:
            return self._update_git_script(script_info, display_name, force, exact, refresh_deps)

    def update_all(
        self, force: bool, exact: bool | None, refresh_deps: bool = False
    ) -> list[tuple[str, str]]:
        """
        Update all installed scripts.

        Args:
            force: Force reinstall all scripts
            exact: Use --exact flag in shebang
            refresh_deps: Re-resolve dependencies from repository

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
            display_name = script_info.display_name

            # Skip local scripts (they need manual source updates)
            if script_info.source_type == SourceType.LOCAL:
                results.append((display_name, "skipped (local)"))
                continue

            # Verify git available once
            if not git_checked:
                handle_git_error(self.console, lambda: verify_git_available())
                git_checked = True

            try:
                status = self._update_git_script_internal(script_info, force, exact, refresh_deps)
                results.append((display_name, status))
            except (GitError, ScriptInstallerError) as e:
                results.append((display_name, f"Error: {e}"))

        return results

    def _update_local_script(
        self, script_info: ScriptInfo, script_name: str, exact: bool | None, refresh_deps: bool = False
    ) -> tuple[str, str]:
        """Update a local script."""
        if not script_info.source_path or not script_info.source_path.exists():
            self.console.print(f"[red]Error:[/red] Source directory not found: {script_info.source_path}")
            self.console.print("The original source directory may have been moved or deleted.")
            raise FileNotFoundError(f"Source directory not found: {script_info.source_path}")

        try:
            with progress_spinner("Updating from source...", self.console):
                # Re-copy from source directory
                if script_info.copy_parent_dir:
                    # Copy entire directory contents
                    copy_directory_contents(script_info.source_path, script_info.repo_path)
                else:
                    # Copy just the script file
                    import shutil

                    source_script = script_info.source_path / script_name
                    dest_script = script_info.repo_path / script_name
                    dest_script.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source_script, dest_script)

            # Resolve dependencies
            dependencies = script_info.dependencies
            if refresh_deps:
                dependencies = resolve_dependencies(None, script_info.repo_path, script_info.source_path)
                if dependencies != script_info.dependencies:
                    self.console.print(
                        f"[cyan]Dependencies refreshed:[/cyan] {', '.join(dependencies) or 'none'}"
                    )

            # Reinstall script (preserve alias if it exists)
            script_path = script_info.repo_path / script_name
            # Extract alias from existing symlink if it differs from original name
            script_alias = None
            if script_info.symlink_path and script_info.symlink_path.name != script_name:
                script_alias = script_info.symlink_path.name

            install_config = InstallConfig(
                install_dir=self.config.install_dir,
                auto_chmod=self.config.auto_chmod,
                auto_symlink=self.config.auto_symlink,
                verify_after_install=self.config.verify_after_install,
                use_exact=exact if exact is not None else self.config.use_exact_flag,
                script_alias=script_alias,
            )
            symlink_path, shadow_warning = install_script(
                script_path,
                dependencies,
                install_config,
            )

            # Show shadow warning if any
            if shadow_warning:
                self.console.print(f"[yellow]Warning:[/yellow] {shadow_warning}")

            # Update state
            script_info.dependencies = dependencies
            script_info.installed_at = datetime.now()
            script_info.symlink_path = symlink_path
            self.state_manager.add_script(script_info)

            return (script_info.display_name, "updated")

        except (ScriptInstallerError, Exception) as e:
            return (script_info.display_name, f"Error: {e}")

    def _update_git_script(
        self,
        script_info: ScriptInfo,
        script_name: str,
        force: bool,
        exact: bool | None,
        refresh_deps: bool = False,
    ) -> tuple[str, str]:
        """Update a Git script."""
        assert script_info.source_url is not None
        assert script_info.ref is not None

        handle_git_error(self.console, lambda: verify_git_available())
        display_name = script_info.display_name

        try:
            status = self._update_git_script_internal(script_info, force, exact, refresh_deps)
            return (display_name, status)
        except (GitError, ScriptInstallerError) as e:
            return (display_name, f"Error: {e}")

    def _update_git_script_internal(
        self, script_info: ScriptInfo, force: bool, exact: bool | None, refresh_deps: bool = False
    ) -> str:
        """Internal method to update a Git script."""
        assert script_info.source_url is not None
        assert script_info.ref is not None

        # Check if this is a pinned ref (tag or commit)
        is_pinned = script_info.ref_type in ("tag", "commit")

        if is_pinned and not force:
            # Pinned refs don't get updates - they're intentionally fixed
            return f"pinned to {script_info.ref}"

        with progress_spinner("Updating repository...", self.console):
            clone_or_update(
                script_info.source_url,
                script_info.ref,
                script_info.repo_path,
                depth=self.config.clone_depth,
            )

        # Check if there are updates
        new_commit_hash = get_current_commit_hash(script_info.repo_path)

        # For non-pinned refs, get the actual current branch
        if not is_pinned:
            try:
                actual_branch = get_default_branch(script_info.repo_path)
            except GitError:
                actual_branch = script_info.ref
        else:
            # Preserve the original pinned ref
            actual_branch = script_info.ref

        if new_commit_hash == script_info.commit_hash and not force and not refresh_deps:
            return "up-to-date"

        # Resolve dependencies
        dependencies = script_info.dependencies
        if refresh_deps:
            dependencies = resolve_dependencies(None, script_info.repo_path)
            if dependencies != script_info.dependencies:
                self.console.print(
                    f"[cyan]Dependencies refreshed:[/cyan] {', '.join(dependencies) or 'none'}"
                )

        # Reinstall script (preserve alias if it exists)
        script_path = script_info.repo_path / script_info.name
        # Extract alias from existing symlink if it differs from original name
        script_alias = None
        if script_info.symlink_path and script_info.symlink_path.name != script_info.name:
            script_alias = script_info.symlink_path.name

        install_config = InstallConfig(
            install_dir=self.config.install_dir,
            auto_chmod=self.config.auto_chmod,
            auto_symlink=self.config.auto_symlink,
            verify_after_install=self.config.verify_after_install,
            use_exact=exact if exact is not None else self.config.use_exact_flag,
            script_alias=script_alias,
        )
        symlink_path, shadow_warning = install_script(
            script_path,
            dependencies,
            install_config,
        )

        # Show shadow warning if any
        if shadow_warning:
            self.console.print(f"[yellow]Warning:[/yellow] {shadow_warning}")

        # Update state with new commit hash and actual branch
        script_info.dependencies = dependencies
        script_info.commit_hash = new_commit_hash
        script_info.ref = actual_branch
        script_info.installed_at = datetime.now()
        script_info.symlink_path = symlink_path
        self.state_manager.add_script(script_info)

        return "updated"
