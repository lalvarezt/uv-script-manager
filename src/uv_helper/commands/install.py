"""Install command handler for UV-Helper."""

import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from ..config import Config
from ..constants import SourceType
from ..deps import resolve_dependencies
from ..git_manager import (
    GitError,
    clone_or_update,
    get_current_commit_hash,
    get_default_branch,
    parse_git_url,
    verify_git_available,
)
from ..script_installer import (
    ScriptInstallerError,
    add_package_source,
    install_script,
)
from ..state import ScriptInfo, StateManager
from ..utils import (
    ensure_dir,
    expand_path,
    get_repo_name_from_url,
    is_git_url,
    is_local_directory,
    prompt_confirm,
    sanitize_directory_name,
)


class InstallHandler:
    """Handles script installation logic."""

    def __init__(self, config: Config, console: Console):
        """
        Initialize install handler.

        Args:
            config: Application configuration
            console: Rich console for output
        """
        self.config = config
        self.console = console
        self.state_manager = StateManager(config.state_file)

    def install(
        self,
        source: str,
        scripts: tuple[str, ...],
        with_deps: str | None,
        force: bool,
        no_symlink: bool,
        install_dir: Path | None,
        verbose: bool,
        exact: bool | None,
        copy_parent_dir: bool,
        add_source_package: str | None,
    ) -> list[tuple[str, bool, Path | None | str]]:
        """
        Install Python scripts from a Git repository or local directory.

        Args:
            source: Git URL or local directory path
            scripts: Script names to install
            with_deps: Dependencies specification
            force: Force overwrite without confirmation
            no_symlink: Skip symlink creation
            install_dir: Custom installation directory
            verbose: Show detailed output
            exact: Use --exact flag in shebang
            copy_parent_dir: Copy entire parent directory
            add_source_package: Add source as package dependency

        Returns:
            List of (script_name, success, location_or_error) tuples
        """
        # Detect and validate source type
        is_local = is_local_directory(source)
        is_git = is_git_url(source)

        if not is_local and not is_git:
            self.console.print(f"[red]Error:[/red] Invalid source: {source}")
            self.console.print("Source must be either a Git URL or a local directory path.")
            raise ValueError(f"Invalid source: {source}")

        # Validate --add-source-package requirements
        if add_source_package is not None and is_local and not copy_parent_dir:
            error_msg = (
                "[red]Error:[/red] --add-source-package requires --copy-parent-dir "
                "for local sources"
            )
            self.console.print(error_msg)
            raise ValueError("--add-source-package requires --copy-parent-dir for local sources")

        # Check for existing installations
        if not self._check_existing_scripts(scripts, force):
            return []

        # Handle source-specific operations
        if is_git:
            repo_path, source_path, commit_hash, actual_ref, git_ref = self._handle_git_source(
                source
            )
        else:
            repo_path, source_path, commit_hash, actual_ref, git_ref = self._handle_local_source(
                source, scripts, copy_parent_dir
            )

        # Resolve dependencies
        dependencies = self._resolve_dependencies(with_deps, repo_path, source_path, verbose)

        # Determine installation directory
        install_directory = install_dir if install_dir else self.config.install_dir
        ensure_dir(install_directory)

        # Install scripts
        return self._install_scripts(
            scripts,
            repo_path,
            source_path,
            dependencies,
            install_directory,
            is_local,
            is_git,
            copy_parent_dir,
            no_symlink,
            exact,
            add_source_package,
            commit_hash,
            actual_ref,
            git_ref,
        )

    def _check_existing_scripts(self, scripts: tuple[str, ...], force: bool) -> bool:
        """
        Check for existing script installations.

        Args:
            scripts: Script names to check
            force: Whether to force overwrite

        Returns:
            True if should proceed, False if cancelled
        """
        existing_scripts = []
        for script_name in scripts:
            if self.state_manager.get_script(script_name):
                existing_scripts.append(script_name)

        if existing_scripts and not force:
            script_list = ", ".join(existing_scripts)
            self.console.print(
                f"[yellow]Warning:[/yellow] Scripts already installed: {script_list}"
            )
            if not prompt_confirm("Overwrite existing installations?", default=False):
                self.console.print("Installation cancelled.")
                return False

        return True

    def _handle_git_source(self, source: str) -> tuple[Path, None, str, str, Any]:
        """
        Handle Git source installation.

        Args:
            source: Git repository URL

        Returns:
            Tuple of (repo_path, source_path, commit_hash, actual_ref, git_ref)
        """
        git_ref = parse_git_url(source)
        repo_name = get_repo_name_from_url(git_ref.base_url)
        repo_path = self.config.repo_dir / repo_name

        try:
            verify_git_available()
        except GitError as e:
            self.console.print(f"[red]Error:[/red] Git: {e}")
            raise

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=self.console,
            transient=True,
        ) as progress:
            task = progress.add_task("Cloning/updating repository...", total=None)

            try:
                clone_or_update(
                    git_ref.base_url,
                    git_ref.ref_value,
                    repo_path,
                    depth=self.config.clone_depth,
                )
                progress.update(task, completed=True)
            except GitError as e:
                self.console.print(f"[red]Error:[/red] Git: {e}")
                raise

        # Get current commit hash and actual branch
        try:
            commit_hash = get_current_commit_hash(repo_path)
            actual_ref = git_ref.ref_value or get_default_branch(repo_path)
        except GitError as e:
            self.console.print(f"[red]Error:[/red] Git: Failed to get commit hash: {e}")
            raise

        return repo_path, None, commit_hash, actual_ref, git_ref

    def _handle_local_source(
        self, source: str, scripts: tuple[str, ...], copy_parent_dir: bool
    ) -> tuple[Path, Path, None, None, None]:
        """
        Handle local directory source installation.

        Args:
            source: Local directory path
            scripts: Script names to install
            copy_parent_dir: Whether to copy entire parent directory

        Returns:
            Tuple of (repo_path, source_path, commit_hash, actual_ref, git_ref)
        """
        source_path = expand_path(source)

        # Validate source path
        if not source_path.exists():
            self.console.print(f"[red]Error:[/red] Source path does not exist: {source_path}")
            raise FileNotFoundError(f"Source path does not exist: {source_path}")
        if not source_path.is_dir():
            self.console.print(f"[red]Error:[/red] Source path is not a directory: {source_path}")
            raise NotADirectoryError(f"Source path is not a directory: {source_path}")

        if copy_parent_dir:
            repo_path = self._copy_parent_directory(source_path)
        else:
            repo_path = self._create_script_directory(scripts[0])

        return repo_path, source_path, None, None, None

    def _copy_parent_directory(self, source_path: Path) -> Path:
        """
        Copy entire parent directory to repo location.

        Args:
            source_path: Source directory path

        Returns:
            Repository path where directory was copied
        """
        dir_name = sanitize_directory_name(source_path.name)
        repo_path = self.config.repo_dir / dir_name

        if repo_path.exists():
            self.console.print(f"[yellow]Warning:[/yellow] Directory already exists: {repo_path}")
            self.console.print("Existing files will be overwritten.")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=self.console,
            transient=True,
        ) as progress:
            task = progress.add_task("Copying directory...", total=None)

            ensure_dir(repo_path)
            for item in source_path.iterdir():
                dest = repo_path / item.name
                if item.is_dir():
                    if dest.exists():
                        shutil.rmtree(dest)
                    shutil.copytree(item, dest)
                else:
                    shutil.copy2(item, dest)

            progress.update(task, completed=True)

        return repo_path

    def _create_script_directory(self, first_script: str) -> Path:
        """
        Create directory for individual script installation.

        Args:
            first_script: Name of first script to install

        Returns:
            Repository path for scripts
        """
        dir_name = sanitize_directory_name(first_script.replace(".py", ""))
        repo_path = self.config.repo_dir / dir_name

        if repo_path.exists():
            self.console.print(f"[yellow]Warning:[/yellow] Directory already exists: {repo_path}")
            self.console.print("Existing files will be overwritten.")

        ensure_dir(repo_path)
        return repo_path

    def _resolve_dependencies(
        self,
        with_deps: str | None,
        repo_path: Path,
        source_path: Path | None,
        verbose: bool,
    ) -> list[str]:
        """
        Resolve script dependencies.

        Args:
            with_deps: Dependencies specification
            repo_path: Repository path
            source_path: Source path (for local installs)
            verbose: Show detailed output

        Returns:
            List of dependency strings
        """
        try:
            dependencies = resolve_dependencies(with_deps, repo_path, source_path)
            if verbose and dependencies:
                self.console.print(f"Dependencies: {', '.join(dependencies)}")
            return dependencies
        except (FileNotFoundError, OSError) as e:
            self.console.print(f"[red]Error:[/red] Dependencies: {e}")
            raise

    def _install_scripts(
        self,
        scripts: tuple[str, ...],
        repo_path: Path,
        source_path: Path | None,
        dependencies: list[str],
        install_directory: Path,
        is_local: bool,
        is_git: bool,
        copy_parent_dir: bool,
        no_symlink: bool,
        exact: bool | None,
        add_source_package: str | None,
        commit_hash: str | None,
        actual_ref: str | None,
        git_ref: Any,
    ) -> list[tuple[str, bool, Path | None | str]]:
        """
        Install all requested scripts.

        Returns:
            List of installation results
        """
        results = []
        for script_name in scripts:
            result = self._install_single_script(
                script_name,
                repo_path,
                source_path,
                dependencies,
                install_directory,
                is_local,
                is_git,
                copy_parent_dir,
                no_symlink,
                exact,
                add_source_package,
                commit_hash,
                actual_ref,
                git_ref,
            )
            results.append(result)

        return results

    def _install_single_script(
        self,
        script_name: str,
        repo_path: Path,
        source_path: Path | None,
        dependencies: list[str],
        install_directory: Path,
        is_local: bool,
        is_git: bool,
        copy_parent_dir: bool,
        no_symlink: bool,
        exact: bool | None,
        add_source_package: str | None,
        commit_hash: str | None,
        actual_ref: str | None,
        git_ref: Any,
    ) -> tuple[str, bool, Path | None | str]:
        """Install a single script."""
        # For local sources without copy-parent-dir, copy script from source
        if is_local and not copy_parent_dir:
            assert source_path is not None
            source_script = source_path / script_name
            if not source_script.exists():
                self.console.print(
                    f"[red]Error:[/red] Script '{script_name}' not found at: {source_script}"
                )
                return (script_name, False, "Not found")

            # Copy to repo_path
            dest_script = repo_path / script_name
            dest_script.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_script, dest_script)
            script_path = dest_script
        else:
            script_path = repo_path / script_name

        # Check if script exists
        if not script_path.exists():
            self.console.print(
                f"[red]Error:[/red] Script '{script_name}' not found at: {script_path}"
            )
            return (script_name, False, "Not found")

        try:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=self.console,
                transient=True,
            ) as progress:
                task = progress.add_task(f"Installing {script_name}...", total=None)

                # Add source package if requested
                if add_source_package is not None:
                    pkg_name = add_source_package if add_source_package else repo_path.name
                    add_package_source(script_path, pkg_name, repo_path)
                    if pkg_name not in dependencies:
                        dependencies.append(pkg_name)

                symlink_path = install_script(
                    script_path,
                    dependencies,
                    install_directory,
                    auto_chmod=self.config.auto_chmod,
                    auto_symlink=not no_symlink and self.config.auto_symlink,
                    verify_after_install=self.config.verify_after_install,
                    use_exact=exact if exact is not None else self.config.use_exact_flag,
                )

                progress.update(task, completed=True)

            # Save to state
            if is_git:
                assert git_ref is not None
                script_info = ScriptInfo(
                    name=script_name,
                    source_type=SourceType.GIT,
                    source_url=git_ref.base_url,
                    ref=actual_ref,
                    installed_at=datetime.now(),
                    repo_path=repo_path,
                    symlink_path=symlink_path,
                    dependencies=dependencies,
                    commit_hash=commit_hash,
                )
            else:
                script_info = ScriptInfo(
                    name=script_name,
                    source_type=SourceType.LOCAL,
                    installed_at=datetime.now(),
                    repo_path=repo_path,
                    symlink_path=symlink_path,
                    dependencies=dependencies,
                    source_path=source_path,
                    copy_parent_dir=copy_parent_dir,
                )
            self.state_manager.add_script(script_info)

            return (script_name, True, symlink_path)

        except ScriptInstallerError as e:
            self.console.print(f"[red]Error:[/red] Installing '{script_name}': {e}")
            return (script_name, False, str(e))
