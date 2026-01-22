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
from .display import (
    display_install_results,
    display_script_details,
    display_scripts_table,
    display_update_results,
)
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
@click.option(
    "--no-deps",
    is_flag=True,
    help="Skip all dependency resolution (ignore requirements.txt and --with)",
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
    no_deps: bool,
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

        \b
        # Install without any dependencies
        uv-helper install https://github.com/user/repo --script app.py --no-deps
    """
    config = ctx.obj["config"]

    # Validate --alias flag usage
    if alias is not None and len(script) != 1:
        console.print("[red]Error:[/red] --alias can only be used when installing a single script")
        sys.exit(1)

    handler = InstallHandler(config, console)

    try:
        request = InstallRequest(
            with_deps=None if no_deps else with_deps,
            force=force,
            no_symlink=no_symlink,
            install_dir=install_dir,
            verbose=verbose,
            exact=exact,
            copy_parent_dir=copy_parent_dir,
            add_source_package=add_source_package,
            alias=alias,
            no_deps=no_deps,
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
@click.pass_context
def show(ctx: click.Context, script_name: str) -> None:
    """
    Show detailed information about an installed script.

    Displays comprehensive information about a specific script including
    source details, paths, installation date, and dependencies.

    Examples:

        \b
        # Show details for a script
        uv-helper show myscript

        \b
        # Show details using alias
        uv-helper show myalias
    """
    config = ctx.obj["config"]
    state_manager = StateManager(config.state_file)

    script_info = state_manager.get_script_flexible(script_name)
    if script_info is None:
        console.print(f"[red]Error:[/red] Script '{script_name}' not found.")
        sys.exit(1)
        return  # Help type checker understand this is unreachable

    display_script_details(script_info, console)


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
@click.option(
    "--refresh-deps",
    is_flag=True,
    help="Re-resolve dependencies from repository (reads requirements.txt again)",
)
@click.pass_context
def update(ctx: click.Context, script_name: str, force: bool, exact: bool | None, refresh_deps: bool) -> None:
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

        \b
        # Update and re-resolve dependencies from requirements.txt
        uv-helper update myscript --refresh-deps
    """
    config = ctx.obj["config"]
    handler = UpdateHandler(config, console)

    try:
        result = handler.update(script_name, force, exact, refresh_deps)
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
@click.option(
    "--refresh-deps",
    is_flag=True,
    help="Re-resolve dependencies from repository (reads requirements.txt again)",
)
@click.pass_context
def update_all(ctx: click.Context, force: bool, exact: bool | None, refresh_deps: bool) -> None:
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

        \b
        # Update all and re-resolve dependencies from requirements.txt
        uv-helper update-all --refresh-deps
    """
    config = ctx.obj["config"]
    handler = UpdateHandler(config, console)

    try:
        results = handler.update_all(force, exact, refresh_deps)
        if results:
            display_update_results(results, console)
    except ScriptInstallerError:
        sys.exit(1)


@cli.command("export")
@click.option(
    "-o",
    "--output",
    type=click.Path(path_type=Path),
    help="Output file path (default: stdout)",
)
@click.pass_context
def export_scripts(ctx: click.Context, output: Path | None) -> None:
    """
    Export installed scripts to a JSON file for backup or sharing.

    Creates a JSON file containing all installed scripts with their
    source URLs, refs, and installation options. This file can be
    used with 'uv-helper import' to reinstall scripts on another machine.

    Examples:

        \b
        # Export to stdout
        uv-helper export

        \b
        # Export to a file
        uv-helper export -o scripts.json
    """
    import json

    from .constants import SourceType

    config = ctx.obj["config"]
    state_manager = StateManager(config.state_file)

    scripts = state_manager.list_scripts()

    if not scripts:
        console.print("No scripts installed.")
        return

    scripts_list: list[dict[str, str | list[str] | bool | None]] = []
    export_data: dict[str, int | list[dict[str, str | list[str] | bool | None]]] = {
        "version": 1,
        "scripts": scripts_list,
    }

    for script in scripts:
        script_data: dict[str, str | list[str] | bool | None] = {
            "name": script.name,
            "source_type": script.source_type.value,
        }

        if script.source_type == SourceType.GIT:
            # Build source URL with ref if present
            source_url = script.source_url
            if script.ref:
                script_data["ref"] = script.ref
            script_data["source"] = source_url
        else:
            script_data["source"] = str(script.source_path) if script.source_path else None
            script_data["copy_parent_dir"] = script.copy_parent_dir

        if script.dependencies:
            script_data["dependencies"] = script.dependencies

        # Check for alias
        if script.symlink_path and script.symlink_path.name != script.name:
            script_data["alias"] = script.symlink_path.name

        scripts_list.append(script_data)

    json_output = json.dumps(export_data, indent=2)

    if output:
        output.write_text(json_output)
        console.print(f"[green]✓[/green] Exported {len(scripts)} script(s) to {output}")
    else:
        console.print(json_output)


@cli.command("import")
@click.argument("file", type=click.Path(exists=True, path_type=Path))
@click.option("--force", "-f", is_flag=True, help="Force overwrite existing scripts without confirmation")
@click.option("--dry-run", is_flag=True, help="Show what would be installed without actually installing")
@click.pass_context
def import_scripts(ctx: click.Context, file: Path, force: bool, dry_run: bool) -> None:
    """
    Import and install scripts from an export file.

    Reads a JSON file created by 'uv-helper export' and installs
    all scripts defined in it. Useful for setting up a new machine
    or sharing script configurations.

    Examples:

        \b
        # Import scripts from a file
        uv-helper import scripts.json

        \b
        # Preview what would be installed
        uv-helper import scripts.json --dry-run

        \b
        # Force overwrite existing scripts
        uv-helper import scripts.json --force
    """
    import json

    from .constants import SourceType

    config = ctx.obj["config"]

    try:
        data = json.loads(file.read_text())
    except json.JSONDecodeError as e:
        console.print(f"[red]Error:[/red] Invalid JSON file: {e}")
        sys.exit(1)

    if "scripts" not in data:
        console.print("[red]Error:[/red] Invalid export file: missing 'scripts' key")
        sys.exit(1)

    scripts = data["scripts"]
    if not scripts:
        console.print("No scripts to import.")
        return

    if dry_run:
        console.print("[bold]Dry run - the following scripts would be installed:[/bold]\n")
        for script_data in scripts:
            name = script_data.get("name", "unknown")
            source = script_data.get("source", "unknown")
            ref = script_data.get("ref", "")
            alias = script_data.get("alias")

            ref_str = f"@{ref}" if ref else ""
            alias_str = f" (as {alias})" if alias else ""
            console.print(f"  • {name}{alias_str} from {source}{ref_str}")
        return

    console.print(f"Importing {len(scripts)} script(s)...\n")

    handler = InstallHandler(config, console)
    results = []

    for script_data in scripts:
        name = script_data.get("name")
        source = script_data.get("source")
        source_type = script_data.get("source_type", "git")
        ref = script_data.get("ref")
        deps = script_data.get("dependencies", [])
        alias = script_data.get("alias")
        copy_parent_dir = script_data.get("copy_parent_dir", False)

        if not name or not source:
            results.append((name or "unknown", False, "Missing name or source"))
            continue

        # Build source URL with ref for Git sources
        if source_type == SourceType.GIT.value and ref:
            # Use # for branch-like refs, @ for tag-like refs
            if ref.startswith("v") or ref[0].isdigit():
                source = f"{source}@{ref}"
            else:
                source = f"{source}#{ref}"

        try:
            request = InstallRequest(
                with_deps=",".join(deps) if deps else None,
                force=force,
                no_symlink=False,
                install_dir=None,
                verbose=False,
                exact=None,
                copy_parent_dir=copy_parent_dir,
                add_source_package=None,
                alias=alias,
            )
            result = handler.install(source=source, scripts=(name,), request=request)
            results.extend(result)
        except (ValueError, FileNotFoundError, NotADirectoryError) as e:
            results.append((name, False, str(e)))

    display_install_results(results, config.install_dir, console)


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
