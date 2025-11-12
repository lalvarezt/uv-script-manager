"""CLI interface for UV-Helper."""

import sys
from pathlib import Path

# Runtime version check - must be before other imports
if sys.version_info < (3, 11):
    print("Error: UV-Helper requires Python 3.11 or higher", file=sys.stderr)
    version = f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    print(f"Current version: {version}", file=sys.stderr)
    print("\nPlease upgrade your Python installation:", file=sys.stderr)
    print("  https://www.python.org/downloads/", file=sys.stderr)
    sys.exit(1)

import click
from rich.console import Console

from . import __version__
from .commands import InstallHandler, InstallRequest, RemoveHandler, UpdateHandler
from .config import load_config
from .display import display_install_results, display_scripts_table, display_update_results
from .script_installer import ScriptInstallerError, verify_uv_available
from .state import StateManager

console = Console()


@click.group()
@click.version_option(version=__version__)
@click.option(
    "--config",
    type=click.Path(exists=True, path_type=Path),
    help="Custom config file path",
)
@click.pass_context
def cli(ctx: click.Context, config: Path | None) -> None:
    """UV-Helper: Install and manage Python scripts from Git repositories."""
    ctx.ensure_object(dict)

    # Load configuration
    try:
        ctx.obj["config"] = load_config(config)
    except (FileNotFoundError, ValueError, OSError, PermissionError) as e:
        console.print(f"[red]Error:[/red] Configuration: {e}")
        sys.exit(1)

    # Verify required tools
    try:
        verify_uv_available()
    except ScriptInstallerError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


@cli.command()
@click.argument("git-url")
@click.option(
    "--script",
    "-s",
    multiple=True,
    required=True,
    help="Script names to install (can be specified multiple times)",
)
@click.option(
    "--with",
    "-w",
    "with_deps",
    help="Dependencies: requirements.txt path or comma-separated libs",
)
@click.option("--force", "-f", is_flag=True, help="Force overwrite existing scripts without confirmation")
@click.option("--no-symlink", is_flag=True, help="Skip creating symlinks in install directory")
@click.option(
    "--install-dir",
    type=click.Path(path_type=Path),
    help="Custom installation directory (overrides config)",
)
@click.option("-v", "--verbose", is_flag=True, help="Show dependency resolution details")
@click.option(
    "--exact/--no-exact",
    default=None,
    help="Use --exact flag in shebang for precise dependency management (default: from config)",
)
@click.option(
    "--copy-parent-dir",
    is_flag=True,
    help="For local sources: copy entire parent directory instead of just the script",
)
@click.option(
    "--add-source-package",
    default=None,
    help="Add source as a local package dependency (optional: specify package name)",
)
@click.option(
    "--alias",
    default=None,
    help="Custom name for the installed script (can only be used with a single script)",
)
@click.pass_context
def install(
    ctx: click.Context,
    git_url: str,
    script: tuple[str, ...],
    with_deps: str | None,
    force: bool,
    no_symlink: bool,
    install_dir: Path | None,
    verbose: bool,
    exact: bool | None,
    copy_parent_dir: bool,
    add_source_package: str | None,
    alias: str | None,
) -> None:
    """
    Install Python scripts from a Git repository or local directory.

    Downloads the specified repository (or copies from local directory),
    processes the requested scripts, adds dependencies, modifies shebangs
    to use 'uv run --script', and creates symlinks in the install directory.

    Examples:

        \b
        # Install from Git repository
        uv-helper install https://github.com/user/repo --script myscript.py

        \b
        # Install from local directory
        uv-helper install /path/to/scripts --script app.py

        \b
        # Install from local directory, copying entire parent directory
        uv-helper install /path/to/pyhprof --script spring_heapdumper.py --copy-parent-dir

        \b
        # Install with local package as dependency
        uv-helper install /path/to/pyhprof --script spring_heapdumper.py \\
            --copy-parent-dir --add-source-package=pyhprof

        \b
        # Install from Git repo and add as package dependency
        uv-helper install https://github.com/user/repo --script app.py \\
            --add-source-package=mypackage

        \b
        # Install multiple scripts
        uv-helper install https://github.com/user/repo --script script1.py --script script2.py

        \b
        # Install with dependencies from requirements.txt
        uv-helper install https://github.com/user/repo --script app.py --with requirements.txt

        \b
        # Install from a specific branch or tag
        uv-helper install https://github.com/user/repo#dev --script app.py
        uv-helper install https://github.com/user/repo@v1.0.0 --script app.py

        \b
        # Install with custom alias
        uv-helper install https://github.com/user/repo --script long_script_name.py --alias short
    """
    config = ctx.obj["config"]

    # Validate --alias flag usage
    if alias is not None and len(script) != 1:
        console.print("[red]Error:[/red] --alias can only be used when installing a single script")
        sys.exit(1)

    handler = InstallHandler(config, console)

    try:
        request = InstallRequest(
            with_deps=with_deps,
            force=force,
            no_symlink=no_symlink,
            install_dir=install_dir,
            verbose=verbose,
            exact=exact,
            copy_parent_dir=copy_parent_dir,
            add_source_package=add_source_package,
            alias=alias,
        )
        results = handler.install(source=git_url, scripts=script, request=request)

        install_directory = install_dir if install_dir else config.install_dir
        display_install_results(results, install_directory, console)
    except (ValueError, FileNotFoundError, NotADirectoryError):
        sys.exit(1)


@cli.command("list")
@click.option(
    "-v", "--verbose", is_flag=True, help="Show detailed information (commit hash and dependencies)"
)
@click.option("--tree", is_flag=True, help="Display scripts grouped by source in a tree view")
@click.pass_context
def list_scripts(ctx: click.Context, verbose: bool, tree: bool) -> None:
    """
    List all installed scripts with their details.

    Displays information about installed scripts including name, source URL,
    installation date, current commit hash, and symlink location.

    Examples:

        \b
        # List all scripts in table format (default)
        uv-helper list

        \b
        # List with verbose output showing commit hash and dependencies
        uv-helper list -v

        \b
        # Display scripts grouped by source in a tree view
        uv-helper list --tree

        \b
        # Tree view with verbose details
        uv-helper list --tree -v
    """
    from rich.tree import Tree

    from .constants import SourceType

    config = ctx.obj["config"]
    state_manager = StateManager(config.state_file)

    scripts = state_manager.list_scripts()

    if not scripts:
        console.print("No scripts installed.")
        return

    if tree:
        # Group scripts by source
        groups: dict[str, list] = {}
        for script in scripts:
            if script.source_type == SourceType.GIT:
                key = script.source_url or "unknown"
            else:
                key = str(script.source_path) if script.source_path else "local"

            if key not in groups:
                groups[key] = []
            groups[key].append(script)

        # Display tree
        tree_view = Tree("[bold]Installed Scripts by Source[/bold]")

        for source, source_scripts in sorted(groups.items()):
            # Shorten Git URLs
            if source.startswith("http"):
                display_source = "/".join(source.split("/")[-2:])
            else:
                display_source = source

            source_node = tree_view.add(f"[magenta]{display_source}[/magenta]")

            for script in sorted(source_scripts, key=lambda s: s.name):
                # Determine display name with alias indication
                if script.symlink_path:
                    symlink_name = script.symlink_path.name
                    # Show alias relationship if names differ
                    if symlink_name != script.name:
                        name = f"{symlink_name} -> {script.name}"
                    else:
                        name = symlink_name
                else:
                    name = script.name

                if verbose:
                    # Show detailed info in verbose mode
                    details = []
                    if script.commit_hash:
                        details.append(f"commit: {script.commit_hash}")
                    if script.dependencies:
                        details.append(f"{len(script.dependencies)} deps")
                    details.append(f"installed: {script.installed_at.strftime('%Y-%m-%d')}")

                    details_str = f" ({', '.join(details)})" if details else ""
                    source_node.add(f"[cyan]{name}[/cyan]{details_str}")
                else:
                    # Simple view - just show the name
                    source_node.add(f"[cyan]{name}[/cyan]")

        console.print(tree_view)
    else:
        display_scripts_table(scripts, verbose, console)


@cli.command()
@click.argument("script-name")
@click.option("--clean-repo", "-c", is_flag=True, help="Remove repository if no other scripts use it")
@click.option("--force", "-f", is_flag=True, help="Skip confirmation prompt")
@click.pass_context
def remove(
    ctx: click.Context,
    script_name: str,
    clean_repo: bool,
    force: bool,
) -> None:
    """
    Remove an installed script and optionally clean up its repository.

    Removes the script's symlink from the bin directory and updates the
    installation state. If --clean-repo is specified and no other scripts
    from the same repository are installed, removes the repository as well.

    Examples:

        \b
        # Remove a script (keeps repository for other scripts)
        uv-helper remove myscript

        \b
        # Remove script and clean up repository if unused
        uv-helper remove myscript --clean-repo

        \b
        # Skip confirmation prompt
        uv-helper remove myscript --force
    """
    config = ctx.obj["config"]
    handler = RemoveHandler(config, console)

    try:
        handler.remove(script_name, clean_repo, force)
    except (ValueError, ScriptInstallerError):
        sys.exit(1)


@cli.command()
@click.argument("script-name")
@click.option("--force", "-f", is_flag=True, help="Force reinstall even if up-to-date")
@click.option(
    "--exact/--no-exact",
    default=None,
    help="Use --exact flag in shebang for precise dependency management (default: from config)",
)
@click.pass_context
def update(ctx: click.Context, script_name: str, force: bool, exact: bool | None) -> None:
    """
    Update an installed script to the latest version from its repository.

    Fetches the latest changes from the script's Git repository and checks
    if the commit hash has changed. If an update is available (or --force
    is specified), reinstalls the script with the new version.

    Examples:

        \b
        # Update a script if newer version available
        uv-helper update myscript

        \b
        # Force reinstall even if already up-to-date
        uv-helper update myscript --force
    """
    config = ctx.obj["config"]
    handler = UpdateHandler(config, console)

    try:
        result = handler.update(script_name, force, exact)
        display_update_results([result], console)
    except (ValueError, FileNotFoundError, ScriptInstallerError):
        sys.exit(1)


@cli.command("update-all")
@click.option("--force", "-f", is_flag=True, help="Force reinstall all scripts")
@click.option(
    "--exact/--no-exact",
    default=None,
    help="Use --exact flag in shebang for precise dependency management (default: from config)",
)
@click.pass_context
def update_all(ctx: click.Context, force: bool, exact: bool | None) -> None:
    """
    Update all installed scripts to their latest versions.

    Iterates through all installed scripts and updates each one by fetching
    the latest changes from their respective Git repositories. Displays a
    summary table showing which scripts were updated and their status.

    Examples:

        \b
        # Update all scripts if newer versions are available
        uv-helper update-all

        \b
        # Force reinstall all scripts
        uv-helper update-all --force
    """
    config = ctx.obj["config"]
    handler = UpdateHandler(config, console)

    try:
        results = handler.update_all(force, exact)
        if results:
            display_update_results(results, console)
    except ScriptInstallerError:
        sys.exit(1)


@cli.command("doctor")
@click.option("--repair", is_flag=True, help="Automatically repair state issues")
@click.pass_context
def doctor(ctx: click.Context, repair: bool) -> None:
    """
    Run diagnostics and show system health information.

    Displays configuration paths, verifies system dependencies, and validates
    state integrity. Optionally repairs issues found during validation.

    Examples:

        \b
        # Run diagnostics
        uv-helper doctor

        \b
        # Run diagnostics and repair issues
        uv-helper doctor --repair
    """
    from rich.table import Table

    config = ctx.obj["config"]
    state_manager = StateManager(config.state_file)

    # Configuration paths section
    console.print("\n[bold]Configuration[/bold]")
    config_table = Table(show_header=False, box=None, padding=(0, 2))
    config_table.add_column("Label", style="dim")
    config_table.add_column("Path")
    config_table.add_column("Status", justify="right")

    from .config import get_config_path

    config_path = get_config_path()
    config_exists = config_path.exists()
    config_table.add_row(
        "Config file:",
        str(config_path),
        "[green]✓[/green]" if config_exists else "[red]✗[/red]",
    )

    repo_dir_exists = config.repo_dir.exists()
    config_table.add_row(
        "Repository storage:",
        str(config.repo_dir),
        "[green]✓[/green]" if repo_dir_exists else "[yellow]![/yellow]",
    )

    install_dir_exists = config.install_dir.exists()
    config_table.add_row(
        "Install directory:",
        str(config.install_dir),
        "[green]✓[/green]" if install_dir_exists else "[yellow]![/yellow]",
    )

    state_file_exists = config.state_file.exists()
    config_table.add_row(
        "State database:",
        str(config.state_file),
        "[green]✓[/green]" if state_file_exists else "[yellow]![/yellow]",
    )

    console.print(config_table)

    # System dependencies section
    console.print("\n[bold]System Dependencies[/bold]")
    deps_table = Table(show_header=False, box=None, padding=(0, 2))
    deps_table.add_column("Label", style="dim")
    deps_table.add_column("Status", justify="right")

    try:
        verify_uv_available()
        deps_table.add_row("uv (Python package manager):", "[green]✓ Available[/green]")
    except ScriptInstallerError:
        deps_table.add_row("uv (Python package manager):", "[red]✗ Not found[/red]")

    import shutil

    git_available = shutil.which("git") is not None
    deps_table.add_row(
        "git (Version control):", "[green]✓ Available[/green]" if git_available else "[red]✗ Not found[/red]"
    )

    console.print(deps_table)

    # State validation section
    console.print("\n[bold]State Validation[/bold]")
    issues = state_manager.validate_state()

    if not issues:
        console.print("[green]✓[/green] No issues found - state is healthy")
    else:
        console.print(f"[yellow]![/yellow] Found {len(issues)} issue(s):\n")
        for issue in issues:
            console.print(f"  • {issue}")

        if repair:
            console.print("\n[cyan]Repairing state...[/cyan]")
            report = state_manager.repair_state(auto_fix=True)

            console.print("\n[green]✓ Repair complete[/green]")
            if report["broken_symlinks_removed"] > 0:
                console.print(f"  • Removed {report['broken_symlinks_removed']} broken symlink(s)")
            if report["missing_scripts_removed"] > 0:
                removed_count = report["missing_scripts_removed"]
                console.print(f"  • Removed {removed_count} missing script(s) from database")
        else:
            console.print("\n[dim]Run 'uv-helper doctor --repair' to fix these issues[/dim]")

    console.print()


if __name__ == "__main__":
    cli()
