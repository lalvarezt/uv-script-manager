"""Update command handlers for UV-Helper."""

from datetime import datetime
from pathlib import Path

from rich.console import Console

from ..config import Config
from ..constants import SourceType
from ..deps import resolve_dependencies
from ..display import format_local_change_label
from ..git_manager import (
    GitError,
    clone_or_update,
    get_current_commit_hash,
    get_default_branch,
    get_remote_commit_hash,
    verify_git_available,
)
from ..local_changes import clear_managed_script_changes, get_local_change_state
from ..script_installer import InstallConfig, ScriptInstallerError, install_script
from ..state import ScriptInfo, StateManager
from ..update_status import (
    UPDATE_STATUS_SKIPPED_LOCAL,
    UPDATE_STATUS_UP_TO_DATE,
    UPDATE_STATUS_UPDATED,
    UPDATE_STATUS_WOULD_UPDATE,
    UPDATE_STATUS_WOULD_UPDATE_LOCAL_CHANGES,
    make_error_status,
    make_pinned_status,
)
from ..utils import copy_directory_contents, copy_script_file, handle_git_error, progress_spinner


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
        self,
        script_name: str,
        force: bool,
        exact: bool | None,
        refresh_deps: bool = False,
        dry_run: bool = False,
    ) -> tuple[str, str] | tuple[str, str, str]:
        """
        Update a single script.

        Args:
            script_name: Name of script to update (can be original name or alias)
            force: Force reinstall even if up-to-date
            exact: Use --exact flag in shebang
            refresh_deps: Re-resolve dependencies from repository
            dry_run: Show what would be updated without applying changes

        Returns:
            Tuple of (script_name, status) or (script_name, status, local_changes)
        """
        # Check if script exists - try by original name or symlink name
        script_info = self.state_manager.get_script_flexible(script_name)
        if not script_info:
            self.console.print(f"[red]Error:[/red] Script '{script_name}' not found.")
            raise ValueError(f"Script '{script_name}' not found")

        display_name = script_info.display_name

        if dry_run:
            if script_info.source_type == SourceType.LOCAL:
                return self._local_skip_dry_run_result(display_name)

            handle_git_error(self.console, lambda: verify_git_available())
            return self._build_git_dry_run_result(script_info, force, refresh_deps)

        # Branch based on source type (use actual script name from state, not user input)
        if script_info.source_type == SourceType.LOCAL:
            return self._update_local_script(script_info, exact, refresh_deps)
        else:
            return self._update_git_script(script_info, force, exact, refresh_deps)

    def update_all(
        self,
        force: bool,
        exact: bool | None,
        refresh_deps: bool = False,
        dry_run: bool = False,
        show_summary: bool = True,
    ) -> list[tuple[str, str] | tuple[str, str, str]]:
        """
        Update all installed scripts.

        Args:
            force: Force reinstall all scripts
            exact: Use --exact flag in shebang
            refresh_deps: Re-resolve dependencies from repository
            dry_run: Show what would be updated without applying changes
            show_summary: Whether to print summary heading text

        Returns:
            List of (script_name, status) tuples, or
            (script_name, status, local_changes) tuples in dry-run mode
        """
        scripts = self.state_manager.list_scripts()

        if not scripts:
            self.console.print("No scripts installed.")
            return []

        if show_summary:
            if dry_run:
                self.console.print(f"Checking {len(scripts)} script(s) for updates...")
            else:
                self.console.print(f"Updating {len(scripts)} script(s)...")

        results = []
        git_checked = False

        for script_info in scripts:
            display_name = script_info.display_name

            # Skip local scripts (they need manual source updates)
            if script_info.source_type == SourceType.LOCAL:
                if dry_run:
                    results.append(self._local_skip_dry_run_result(display_name))
                else:
                    results.append(self._local_skip_result(display_name))
                continue

            # Verify git available once
            if not git_checked:
                handle_git_error(self.console, lambda: verify_git_available())
                git_checked = True

            try:
                if dry_run:
                    results.append(self._build_git_dry_run_result(script_info, force, refresh_deps))
                else:
                    status = self._update_git_script_internal(script_info, force, exact, refresh_deps)
                    results.append((display_name, status))
            except (GitError, ScriptInstallerError) as e:
                if dry_run:
                    results.append((display_name, make_error_status(str(e)), "Unknown"))
                else:
                    results.append((display_name, make_error_status(str(e))))

        return results

    def _update_local_script(
        self, script_info: ScriptInfo, exact: bool | None, refresh_deps: bool = False
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
                    copy_script_file(script_info.source_path, script_info.name, script_info.repo_path)

            # Resolve dependencies
            dependencies = self._resolve_dependencies_for_update(
                script_info.dependencies,
                script_info.repo_path,
                refresh_deps,
                script_info.source_path,
            )

            # Reinstall script (preserve alias if it exists)
            script_path = script_info.repo_path / script_info.name
            script_alias = self._get_script_alias(script_info, script_info.name)
            symlink_path = self._reinstall_script(script_path, dependencies, exact, script_alias)

            self._persist_script_update(script_info, dependencies, symlink_path)

            return (script_info.display_name, UPDATE_STATUS_UPDATED)

        except Exception as e:
            return (script_info.display_name, make_error_status(str(e)))

    def _update_git_script(
        self,
        script_info: ScriptInfo,
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
            return (display_name, make_error_status(str(e)))

    def _update_git_script_internal(
        self, script_info: ScriptInfo, force: bool, exact: bool | None, refresh_deps: bool = False
    ) -> str:
        """Internal method to update a Git script."""
        assert script_info.source_url is not None
        assert script_info.ref is not None

        # Check if this is a pinned ref (tag or commit)
        is_pinned = script_info.ref_type in ("tag", "commit")

        if is_pinned and not force and not refresh_deps:
            # Pinned refs don't get updates - they're intentionally fixed
            return make_pinned_status(script_info.ref)

        if not is_pinned and not force and not refresh_deps:
            remote_commit_hash = get_remote_commit_hash(script_info.source_url, script_info.ref)
            if remote_commit_hash == script_info.commit_hash:
                return UPDATE_STATUS_UP_TO_DATE

        local_change_state = get_local_change_state(script_info.repo_path, script_info.name)
        if local_change_state == "blocking":
            raise GitError(
                "Repository has custom local changes. Commit, stash, or discard them before updating."
            )
        if local_change_state == "managed":
            cleaned = clear_managed_script_changes(script_info.repo_path, script_info.name)
            if not cleaned:
                raise GitError("Failed to clear uv-managed local script changes before update")

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
            return UPDATE_STATUS_UP_TO_DATE

        # Resolve dependencies
        dependencies = self._resolve_dependencies_for_update(
            script_info.dependencies,
            script_info.repo_path,
            refresh_deps,
        )

        # Reinstall script (preserve alias if it exists)
        script_path = script_info.repo_path / script_info.name
        script_alias = self._get_script_alias(script_info, script_info.name)
        symlink_path = self._reinstall_script(script_path, dependencies, exact, script_alias)

        # Update state with new commit hash and actual branch
        script_info.commit_hash = new_commit_hash
        script_info.ref = actual_branch
        self._persist_script_update(script_info, dependencies, symlink_path)

        return UPDATE_STATUS_UPDATED

    def _get_script_alias(self, script_info: ScriptInfo, script_name: str) -> str | None:
        """Extract preserved alias when it differs from the original script name."""
        if script_info.symlink_path and script_info.symlink_path.name != script_name:
            return script_info.symlink_path.name
        return None

    def _reinstall_script(
        self,
        script_path: Path,
        dependencies: list[str],
        exact: bool | None,
        script_alias: str | None,
    ) -> Path | None:
        """Reinstall a script and return its symlink path."""
        install_config = InstallConfig(
            install_dir=self.config.install_dir,
            auto_chmod=self.config.auto_chmod,
            auto_symlink=self.config.auto_symlink,
            verify_after_install=self.config.verify_after_install,
            use_exact=exact if exact is not None else self.config.use_exact_flag,
            script_alias=script_alias,
        )
        symlink_path, shadow_warning = install_script(script_path, dependencies, install_config)

        if shadow_warning:
            self.console.print(f"[yellow]Warning:[/yellow] {shadow_warning}")

        return symlink_path

    def _persist_script_update(
        self,
        script_info: ScriptInfo,
        dependencies: list[str],
        symlink_path: Path | None,
    ) -> None:
        """Persist common state fields after a successful update."""
        script_info.dependencies = dependencies
        script_info.installed_at = datetime.now()
        script_info.symlink_path = symlink_path
        self.state_manager.add_script(script_info)

    def _resolve_dependencies_for_update(
        self,
        existing_dependencies: list[str],
        repo_path: Path,
        refresh_deps: bool,
        source_path: Path | None = None,
    ) -> list[str]:
        """Resolve update dependencies, optionally re-reading requirements data."""
        if not refresh_deps:
            return existing_dependencies

        dependencies = resolve_dependencies(None, repo_path, source_path)
        if dependencies != existing_dependencies:
            self.console.print(f"[cyan]Dependencies refreshed:[/cyan] {', '.join(dependencies) or 'none'}")
        return dependencies

    def _check_git_script_update_status(
        self,
        script_info: ScriptInfo,
        force: bool,
        refresh_deps: bool,
        local_change_state: str | None = None,
    ) -> str:
        """Check update status for a Git script without mutating local state."""
        assert script_info.source_url is not None
        assert script_info.ref is not None

        is_pinned = script_info.ref_type in ("tag", "commit")

        if is_pinned and not force and not refresh_deps:
            return make_pinned_status(script_info.ref)

        if force or refresh_deps:
            status = UPDATE_STATUS_WOULD_UPDATE
        else:
            remote_commit_hash = get_remote_commit_hash(script_info.source_url, script_info.ref)
            if remote_commit_hash == script_info.commit_hash:
                status = UPDATE_STATUS_UP_TO_DATE
            else:
                status = UPDATE_STATUS_WOULD_UPDATE

        if status == UPDATE_STATUS_WOULD_UPDATE:
            if local_change_state is None:
                local_change_state = get_local_change_state(script_info.repo_path, script_info.name)
            if local_change_state == "blocking":
                return UPDATE_STATUS_WOULD_UPDATE_LOCAL_CHANGES

        return status

    @staticmethod
    def _local_skip_result(display_name: str) -> tuple[str, str]:
        """Build update result tuple for local-only scripts."""
        return (display_name, UPDATE_STATUS_SKIPPED_LOCAL)

    @staticmethod
    def _local_skip_dry_run_result(display_name: str) -> tuple[str, str, str]:
        """Build dry-run update result tuple for local-only scripts."""
        return (display_name, UPDATE_STATUS_SKIPPED_LOCAL, "N/A")

    def _build_git_dry_run_result(
        self,
        script_info: ScriptInfo,
        force: bool,
        refresh_deps: bool,
    ) -> tuple[str, str, str]:
        """Build dry-run update result tuple for a Git-backed script."""
        local_change_state = get_local_change_state(script_info.repo_path, script_info.name)
        status = self._check_git_script_update_status(
            script_info,
            force,
            refresh_deps,
            local_change_state,
        )
        local_changes = format_local_change_label(local_change_state)
        return (script_info.display_name, status, local_changes)
