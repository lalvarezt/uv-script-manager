"""Install command handler for UV-Helper."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pathvalidate import ValidationError, validate_filepath
from rich.console import Console

from ..config import Config
from ..constants import SourceType
from ..deps import resolve_dependencies
from ..git_manager import (
    GitRef,
    clone_or_update,
    get_current_commit_hash,
    get_default_branch,
    parse_git_url,
    verify_git_available,
)
from ..script_installer import (
    InstallConfig,
    ScriptInstallerError,
    add_package_source,
    install_script,
)
from ..state import ScriptInfo, StateManager
from ..utils import (
    copy_directory_contents,
    copy_script_file,
    ensure_dir,
    expand_path,
    get_repo_name_from_url,
    handle_git_error,
    is_git_url,
    is_local_directory,
    progress_spinner,
    prompt_confirm,
    sanitize_directory_name,
)


@dataclass
class InstallationContext:
    """Context for installation source.

    Groups source-related parameters to reduce parameter count in installation methods.
    """

    repo_path: Path
    source_path: Path | None
    is_local: bool
    is_git: bool
    copy_parent_dir: bool
    commit_hash: str | None
    actual_ref: str | None
    git_ref: GitRef | None


@dataclass
class InstallRequest:
    """Installation request parameters.

    Groups all CLI parameters to reduce method parameter count.
    """

    with_deps: str | None
    force: bool
    no_symlink: bool
    install_dir: Path | None
    verbose: bool
    exact: bool | None
    copy_parent_dir: bool
    add_source_package: str | None
    alias: str | None
    no_deps: bool = False


@dataclass
class ScriptInstallOptions:
    """Internal options for script installation.

    Used internally to pass processed options to installation methods.
    """

    dependencies: list[str]
    install_directory: Path
    no_symlink: bool
    exact: bool | None
    add_source_package: str | None
    alias: str | None


class InstallHandler:
    """Handles script installation logic."""

    def __init__(self, config: Config, console: Console) -> None:
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
        request: InstallRequest,
    ) -> list[tuple[str, bool, Path | None | str]]:
        """
        Install Python scripts from a Git repository or local directory.

        Args:
            source: Git URL or local directory path
            scripts: Script names to install
            request: Installation request with all CLI parameters

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
        if request.add_source_package is not None and is_local and not request.copy_parent_dir:
            error_msg = "[red]Error:[/red] --add-source-package requires --copy-parent-dir for local sources"
            self.console.print(error_msg)
            raise ValueError("--add-source-package requires --copy-parent-dir for local sources")

        # Check for existing installations
        if not self._check_existing_scripts(scripts, request.force):
            return []

        # Handle source-specific operations
        if is_git:
            repo_path, source_path, commit_hash, actual_ref, git_ref = self._handle_git_source(source)
        else:
            repo_path, source_path, commit_hash, actual_ref, git_ref = self._handle_local_source(
                source, scripts, request.copy_parent_dir
            )

        # Resolve dependencies (skip if no_deps flag is set)
        if request.no_deps:
            dependencies: list[str] = []
            if request.verbose:
                self.console.print("[cyan]Skipping dependency resolution (--no-deps)[/cyan]")
        else:
            dependencies = self._resolve_dependencies(
                request.with_deps, repo_path, source_path, request.verbose
            )

        # Determine installation directory
        install_directory = request.install_dir or self.config.install_dir
        ensure_dir(install_directory)

        # Create installation context and options
        context = InstallationContext(
            repo_path=repo_path,
            source_path=source_path,
            is_local=is_local,
            is_git=is_git,
            copy_parent_dir=request.copy_parent_dir,
            commit_hash=commit_hash,
            actual_ref=actual_ref,
            git_ref=git_ref,
        )
        options = ScriptInstallOptions(
            dependencies=dependencies,
            install_directory=install_directory,
            no_symlink=request.no_symlink,
            exact=request.exact,
            add_source_package=request.add_source_package,
            alias=request.alias,
        )

        # Install scripts
        return [self._install_single_script(script_name, context, options) for script_name in scripts]

    def _check_existing_scripts(self, scripts: tuple[str, ...], force: bool) -> bool:
        """
        Check for existing script installations.

        Args:
            scripts: Script names to check
            force: Whether to force overwrite

        Returns:
            True if should proceed, False if cancelled
        """
        existing_scripts = [
            script_name for script_name in scripts if self.state_manager.get_script(script_name)
        ]

        if existing_scripts and not force:
            script_list = ", ".join(existing_scripts)
            self.console.print(f"[yellow]Warning:[/yellow] Scripts already installed: {script_list}")
            if not prompt_confirm("Overwrite existing installations?", default=False):
                self.console.print("Installation cancelled.")
                return False

        return True

    def _handle_git_source(self, source: str) -> tuple[Path, None, str, str, GitRef]:
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

        handle_git_error(self.console, lambda: verify_git_available())

        with progress_spinner("Cloning/updating repository...", self.console):
            handle_git_error(
                self.console,
                lambda: clone_or_update(
                    git_ref.base_url,
                    git_ref.ref_value,
                    repo_path,
                    depth=self.config.clone_depth,
                    ref_type=git_ref.ref_type,
                ),
            )

        # Get current commit hash and actual branch
        commit_hash = handle_git_error(
            self.console, lambda: get_current_commit_hash(repo_path), "Failed to get commit hash"
        )
        actual_ref = git_ref.ref_value or handle_git_error(
            self.console, lambda: get_default_branch(repo_path), "Failed to get default branch"
        )

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

        with progress_spinner("Copying directory...", self.console):
            ensure_dir(repo_path)
            copy_directory_contents(source_path, repo_path)

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

    def _install_single_script(
        self,
        script_name: str,
        context: InstallationContext,
        options: ScriptInstallOptions,
    ) -> tuple[str, bool, Path | None | str]:
        """Install a single script.

        Args:
            script_name: Name of the script to install
            context: Installation source context
            options: Installation configuration options

        Returns:
            Tuple of (script_name, success, symlink_path_or_error)
        """
        # Validate script_name to prevent path traversal
        try:
            validate_filepath(script_name, platform="auto")
        except ValidationError as e:
            self.console.print(f"[red]Error:[/red] Invalid script name '{script_name}': {e}")
            return (script_name, False, f"Invalid script name: {e}")

        normalized_parts = Path(script_name.replace("\\", "/")).parts
        is_absolute_like = (
            Path(script_name).is_absolute()
            or script_name.startswith(("/", "\\"))
            or (bool(normalized_parts) and normalized_parts[0].endswith(":"))
        )
        if is_absolute_like or ".." in normalized_parts:
            error = "Path traversal is not allowed"
            self.console.print(f"[red]Error:[/red] Invalid script name '{script_name}': {error}")
            return (script_name, False, f"Invalid script name: {error}")

        # For local sources without copy-parent-dir, copy script from source
        if context.is_local and not context.copy_parent_dir:
            assert context.source_path is not None
            source_script = context.source_path / script_name
            try:
                script_path = copy_script_file(context.source_path, script_name, context.repo_path)
            except (FileNotFoundError, IsADirectoryError):
                self.console.print(f"[red]Error:[/red] Script '{script_name}' not found at: {source_script}")
                return (script_name, False, "Not found")
        else:
            script_path = context.repo_path / script_name

        # Check if script exists
        if not script_path.exists():
            self.console.print(f"[red]Error:[/red] Script '{script_name}' not found at: {script_path}")
            return (script_name, False, "Not found")

        # Track dependencies for state and for uv add --script
        all_deps = list(options.dependencies)

        try:
            with progress_spinner(f"Installing {script_name}...", self.console):
                # Add source package if requested
                if options.add_source_package is not None:
                    pkg_name = (
                        options.add_source_package if options.add_source_package else context.repo_path.name
                    )
                    add_package_source(script_path, pkg_name, context.repo_path)
                    if pkg_name not in all_deps:
                        all_deps.append(pkg_name)

                install_config = InstallConfig(
                    install_dir=options.install_directory,
                    auto_chmod=self.config.auto_chmod,
                    auto_symlink=not options.no_symlink and self.config.auto_symlink,
                    verify_after_install=self.config.verify_after_install,
                    use_exact=options.exact if options.exact is not None else self.config.use_exact_flag,
                    script_alias=options.alias,
                )
                symlink_path, shadow_warning = install_script(script_path, all_deps, install_config)

            # Show shadow warning if any
            if shadow_warning:
                self.console.print(f"[yellow]Warning:[/yellow] {shadow_warning}")

            if context.is_git:
                assert context.git_ref is not None
                script_info = ScriptInfo(
                    name=script_name,
                    source_type=SourceType.GIT,
                    source_url=context.git_ref.base_url,
                    ref=context.actual_ref,
                    ref_type=context.git_ref.ref_type,
                    installed_at=datetime.now(),
                    repo_path=context.repo_path,
                    symlink_path=symlink_path,
                    dependencies=all_deps,
                    commit_hash=context.commit_hash,
                )
            else:
                script_info = ScriptInfo(
                    name=script_name,
                    source_type=SourceType.LOCAL,
                    installed_at=datetime.now(),
                    repo_path=context.repo_path,
                    symlink_path=symlink_path,
                    dependencies=all_deps,
                    source_path=context.source_path,
                    copy_parent_dir=context.copy_parent_dir,
                )
            self.state_manager.add_script(script_info)

            return (script_name, True, symlink_path)

        except ScriptInstallerError as e:
            self.console.print(f"[red]Error:[/red] Installing '{script_name}': {e}")
            return (script_name, False, str(e))
