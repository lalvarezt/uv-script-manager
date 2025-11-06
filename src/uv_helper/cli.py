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
from .commands import InstallHandler, RemoveHandler, UpdateHandler
from .config import load_config
from .constants import JSON_OUTPUT_INDENT
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
@click.option(
    "--force", "-f", is_flag=True, help="Force overwrite existing scripts without confirmation"
)
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
    """
    config = ctx.obj["config"]
    handler = InstallHandler(config, console)

    try:
        results = handler.install(
            source=git_url,
            scripts=script,
            with_deps=with_deps,
            force=force,
            no_symlink=no_symlink,
            install_dir=install_dir,
            verbose=verbose,
            exact=exact,
            copy_parent_dir=copy_parent_dir,
            add_source_package=add_source_package,
        )

        install_directory = install_dir if install_dir else config.install_dir
        display_install_results(results, install_directory, console)
    except (ValueError, FileNotFoundError, NotADirectoryError):
        sys.exit(1)


@cli.command("list")
@click.option(
    "--format",
    type=click.Choice(["table", "json"], case_sensitive=False),
    default="table",
    help="Output format: table (default) or json",
)
@click.option("-v", "--verbose", is_flag=True, help="Show commit hash and dependencies")
@click.pass_context
def list_scripts(ctx: click.Context, format: str, verbose: bool) -> None:
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
        # Output as JSON for scripting
        uv-helper list --format json
    """
    config = ctx.obj["config"]
    state_manager = StateManager(config.state_file)

    scripts = state_manager.list_scripts()

    if not scripts:
        console.print("No scripts installed.")
        return

    if format == "json":
        import json

        # Use Pydantic's model_dump with mode='json' for JSON-compatible output
        output = [script.model_dump(mode="json") for script in scripts]
        print(json.dumps(output, indent=JSON_OUTPUT_INDENT, default=str))
    else:
        display_scripts_table(scripts, verbose, console)


@cli.command()
@click.argument("script-name")
@click.option(
    "--clean-repo", "-c", is_flag=True, help="Remove repository if no other scripts use it"
)
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


if __name__ == "__main__":
    cli()
