"""CLI interface for UV-Helper."""

import json
import os
import shlex
import sys
from pathlib import Path
from typing import cast

# Runtime version check - must be before other imports
if sys.version_info < (3, 11):
    print("Error: UV-Helper requires Python 3.11 or higher", file=sys.stderr)
    version = f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    print(f"Current version: {version}", file=sys.stderr)
    print("\nPlease upgrade your Python installation:", file=sys.stderr)
    print("  https://www.python.org/downloads/", file=sys.stderr)
    sys.exit(1)

import click
from click.shell_completion import CompletionItem
from rich.console import Console

from . import __version__
from .commands import InstallHandler, InstallRequest, RemoveHandler, UpdateHandler
from .config import create_default_config, get_config_path, load_config
from .constants import JSON_OUTPUT_INDENT
from .display import (
    display_install_results,
    display_script_details,
    display_scripts_table,
    display_update_results,
    get_script_display_name,
    get_script_source_display,
    get_script_status_key,
    render_script_status,
)
from .refs import build_ref_suffix
from .script_installer import ScriptInstallerError, verify_uv_available
from .state import StateManager

console = Console()

SCRIPT_CANDIDATE_EXCLUDED_FILES = {
    "__init__.py",
    "__main__.py",
    "setup.py",
    "conftest.py",
    "noxfile.py",
    "fabfile.py",
}
SCRIPT_CANDIDATE_EXCLUDED_PREFIXES = ("test_", "_")
SCRIPT_CANDIDATE_EXCLUDED_SUFFIXES = ("_test.py",)
SCRIPT_CANDIDATE_EXCLUDED_DIRS = {"__pycache__", "venv", ".venv", "node_modules"}


def complete_script_names(
    ctx: click.Context, param: click.Parameter, incomplete: str
) -> list[CompletionItem]:
    """Provide completion for installed script names."""

    def _get_completion_config_path() -> Path | None:
        """Resolve config path for completion from context or COMP_WORDS."""
        current_ctx: click.Context | None = ctx
        while current_ctx is not None:
            config_value = current_ctx.params.get("config") if current_ctx.params else None
            if isinstance(config_value, Path):
                return config_value
            if isinstance(config_value, str) and config_value:
                return Path(config_value)
            current_ctx = current_ctx.parent

        completion_words = os.environ.get("COMP_WORDS")
        if not completion_words:
            return None

        try:
            words = shlex.split(completion_words)
        except ValueError:
            words = completion_words.split()

        for index, word in enumerate(words):
            if word == "--config" and index + 1 < len(words):
                return Path(words[index + 1])
            if word.startswith("--config="):
                _, value = word.split("=", 1)
                if value:
                    return Path(value)

        return None

    try:
        # Try to get config from context, or load it directly
        if ctx.obj and "config" in ctx.obj:
            config = ctx.obj["config"]
        else:
            config_path = _get_completion_config_path() or get_config_path()
            if config_path.exists():
                config = load_config(config_path)
            else:
                config = create_default_config()

        state_manager = StateManager(config.state_file)
        scripts = state_manager.list_scripts()

        completions = []
        seen_names: set[str] = set()

        for script in scripts:
            # Add the original script name
            if script.name.startswith(incomplete) and script.name not in seen_names:
                seen_names.add(script.name)
                completions.append(CompletionItem(script.name, help=script.source_url or "local"))

            # Add alias if different from name
            if script.symlink_path:
                alias = script.symlink_path.name
                if alias != script.name and alias.startswith(incomplete) and alias not in seen_names:
                    seen_names.add(alias)
                    completions.append(CompletionItem(alias, help=f"alias for {script.name}"))

        return completions
    except Exception:
        # Silently fail on any error during completion
        return []


def _is_install_candidate(path: Path, show_all: bool = False) -> bool:
    """Check whether a Python file is a likely installable script."""
    if path.suffix != ".py":
        return False

    parts = path.parts
    if any(part.startswith(".") for part in parts):
        return False
    if any(part in SCRIPT_CANDIDATE_EXCLUDED_DIRS for part in parts):
        return False

    if show_all:
        return True

    if path.name in SCRIPT_CANDIDATE_EXCLUDED_FILES:
        return False
    if path.name.startswith(SCRIPT_CANDIDATE_EXCLUDED_PREFIXES):
        return False
    return not path.name.endswith(SCRIPT_CANDIDATE_EXCLUDED_SUFFIXES)


def _install_hint_sort_key(path: Path) -> tuple[int, int, str]:
    """Rank candidate scripts for the browse install hint."""
    lowered_parts = [part.lower() for part in path.parts]
    parent_parts = lowered_parts[:-1]
    file_name = path.name.lower()

    score = 0

    if len(lowered_parts) == 1:
        score -= 20
    else:
        score += len(lowered_parts) * 2

    if parent_parts and parent_parts[0] in {"scripts", "bin"}:
        score -= 8

    if any(
        part in {"docs", "doc", "tests", "test", "examples", "example", "samples", "sample"}
        for part in parent_parts
    ):
        score += 60

    if file_name in {"main.py", "cli.py", "run.py", "app.py", "tool.py", "server.py", "manage.py"}:
        score -= 30

    if file_name == "__main__.py":
        score -= 25

    return (score, len(lowered_parts), path.as_posix())


def _discover_install_script_candidates(source: str, clone_depth: int) -> list[str]:
    """Discover candidate script paths for interactive install mode."""
    import tempfile

    from .git_manager import GitError, clone_or_update, parse_git_url
    from .utils import expand_path, is_git_url, is_local_directory

    def _collect_from_root(root: Path) -> list[str]:
        """Collect installable Python script paths from a source root."""
        candidates: list[str] = []
        for py_file in root.rglob("*.py"):
            rel_path = py_file.relative_to(root)
            if _is_install_candidate(rel_path):
                candidates.append(rel_path.as_posix())
        return sorted(candidates)

    if is_local_directory(source):
        return _collect_from_root(expand_path(source))

    if is_git_url(source):
        parsed = parse_git_url(source)
        with tempfile.TemporaryDirectory(prefix="uv-helper-install-") as temp_dir:
            repo_path = Path(temp_dir) / "repo"
            try:
                clone_or_update(
                    parsed.base_url,
                    parsed.ref_value,
                    repo_path,
                    depth=clone_depth,
                    ref_type=parsed.ref_type,
                )
            except GitError as e:
                raise ValueError(str(e)) from e
            return _collect_from_root(repo_path)

    return []


def _parse_script_selection(selection: str, max_index: int) -> list[int]:
    """Parse comma-separated numeric selections and ranges."""
    indexes: list[int] = []
    seen: set[int] = set()

    for token in selection.split(","):
        token = token.strip()
        if not token:
            continue

        if "-" in token:
            start_str, end_str = token.split("-", 1)
            if not start_str.isdigit() or not end_str.isdigit():
                raise ValueError(f"Invalid range: {token}")
            start = int(start_str)
            end = int(end_str)
            if start > end:
                raise ValueError(f"Invalid range: {token}")
            values = range(start, end + 1)
        else:
            if not token.isdigit():
                raise ValueError(f"Invalid selection: {token}")
            values = [int(token)]

        for value in values:
            if value < 1 or value > max_index:
                raise ValueError(f"Selection out of range: {value}")
            if value not in seen:
                seen.add(value)
                indexes.append(value)

    if not indexes:
        raise ValueError("No selections provided")

    return indexes


def _is_interactive_terminal() -> bool:
    """Return True when running in an interactive terminal."""
    return sys.stdin.isatty() and sys.stdout.isatty()


def _prompt_for_script_selection(candidates: list[str]) -> tuple[str, ...]:
    """Prompt user to select one or more scripts from candidates."""
    console.print("[bold]No --script provided. Select script(s) to install:[/bold]")
    for index, script_path in enumerate(candidates, start=1):
        console.print(f"  [cyan]{index:>2}[/cyan]. {script_path}")

    while True:
        selection = click.prompt("Select script number(s)", default="1", show_default=True)
        try:
            indexes = _parse_script_selection(selection, len(candidates))
            return tuple(candidates[index - 1] for index in indexes)
        except ValueError as e:
            console.print(f"[red]Error:[/red] {e}. Enter values like [cyan]1[/cyan] or [cyan]1,3-5[/cyan].")


def _filter_and_sort_scripts(
    scripts,
    source_filter: str | None,
    status_filter: str | None,
    ref_filter: str | None,
    sort_by: str,
):
    """Filter and sort scripts for list command output."""
    from .constants import SourceType

    local_changes_cache: dict[tuple[Path, str], str] = {}
    filtered = scripts

    if source_filter:
        source_text = source_filter.lower()
        filtered = [
            script
            for script in filtered
            if source_text
            in (
                (script.source_url or "")
                if script.source_type == SourceType.GIT
                else str(script.source_path or "")
            ).lower()
        ]

    if ref_filter:
        ref_text = ref_filter.lower()
        filtered = [
            script
            for script in filtered
            if script.source_type == SourceType.GIT and ref_text in (script.ref or "").lower()
        ]

    if status_filter:
        status_key = status_filter.lower()
        if status_key == "git":
            filtered = [script for script in filtered if script.source_type == SourceType.GIT]
        else:
            filtered = [
                script
                for script in filtered
                if get_script_status_key(script, local_changes_cache) == status_key
            ]

    if sort_by == "updated":
        filtered = sorted(filtered, key=lambda script: script.installed_at, reverse=True)
    elif sort_by == "source":
        filtered = sorted(
            filtered,
            key=lambda script: (
                (script.source_url or "")
                if script.source_type == SourceType.GIT
                else str(script.source_path or "")
            ).lower(),
        )
    elif sort_by == "status":
        filtered = sorted(
            filtered,
            key=lambda script: (
                get_script_status_key(script, local_changes_cache),
                script.display_name.lower(),
            ),
        )
    else:
        filtered = sorted(filtered, key=lambda script: script.display_name.lower())

    return filtered


def _script_to_json(
    script, local_changes_cache: dict[tuple[Path, str], str] | None = None
) -> dict[str, object]:
    """Serialize script info for JSON responses."""
    from .constants import SourceType

    payload: dict[str, object] = {
        "name": script.name,
        "display_name": script.display_name,
        "source_type": script.source_type.value,
        "source": script.source_url
        if script.source_type == SourceType.GIT
        else str(script.source_path or ""),
        "ref": script.ref,
        "ref_type": script.ref_type,
        "commit_hash": script.commit_hash,
        "installed_at": script.installed_at.isoformat(),
        "dependencies": script.dependencies,
        "repo_path": str(script.repo_path),
        "symlink_path": str(script.symlink_path) if script.symlink_path else None,
        "source_path": str(script.source_path) if script.source_path else None,
        "copy_parent_dir": script.copy_parent_dir,
    }

    status_cache = local_changes_cache if local_changes_cache is not None else {}
    payload["status"] = get_script_status_key(script, status_cache)
    return payload


def _update_results_to_json(results: list[tuple[str, str] | tuple[str, str, str]]) -> list[dict[str, object]]:
    """Serialize update results for JSON responses."""
    payload: list[dict[str, object]] = []
    for result in results:
        if len(result) == 3:
            script_name, status, local_changes = cast(tuple[str, str, str], result)
        else:
            script_name, status = cast(tuple[str, str], result)
            local_changes = None
        payload.append(
            {
                "script": script_name,
                "status": status,
                "local_changes": local_changes,
            }
        )
    return payload


def _build_install_request(
    *,
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
) -> InstallRequest:
    """Build a normalized install request shared by install/import paths."""
    return InstallRequest(
        with_deps=with_deps,
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


def _print_update_all_impact_summary(state_manager: StateManager, dry_run: bool) -> None:
    """Print compact impact summary for update --all."""
    scripts = state_manager.list_scripts()
    if not scripts:
        return

    local_count = sum(1 for script in scripts if script.source_type.value == "local")
    git_count = len(scripts) - local_count
    pinned_count = sum(1 for script in scripts if script.ref_type in ("tag", "commit"))

    console.print("[bold]Impact:[/bold] update --all")
    console.print(f"  Scripts: {len(scripts)} ({git_count} git, {local_count} local-only)")
    if pinned_count:
        console.print(
            "  Pinned refs: "
            f"{pinned_count} (stay pinned unless [cyan]--force[/cyan] or [cyan]--refresh-deps[/cyan])"
        )
    if dry_run:
        console.print("  Mode: dry-run")


def _print_remove_clean_repo_impact_summary(state_manager: StateManager, script_name: str) -> None:
    """Print compact impact summary for remove --clean-repo."""
    script_info = state_manager.get_script_flexible(script_name)
    if script_info is None:
        return

    scripts_from_repo = state_manager.get_scripts_from_repo(script_info.repo_path)
    remaining = max(len(scripts_from_repo) - 1, 0)
    repo_action = "will be removed" if remaining == 0 else f"kept (shared by {remaining} other script(s))"

    console.print("[bold]Impact:[/bold] remove --clean-repo")
    console.print(f"  Script: {script_info.display_name}")
    console.print(f"  Repository: {script_info.repo_path} ({repo_action})")


def _print_needs_attention_hint(scripts) -> None:
    """Print a follow-up hint when one or more scripts need attention."""
    local_changes_cache: dict[tuple[Path, str], str] = {}
    needs_attention = [
        script.display_name
        for script in scripts
        if get_script_status_key(script, local_changes_cache) == "needs-attention"
    ]

    if not needs_attention:
        return

    console.print(
        f"[#ff8c00]Some scripts need attention.[/] [dim]Example: uv-helper show {needs_attention[0]}[/dim]"
    )


@click.group()
@click.version_option(version=__version__)
@click.option(
    "--config",
    type=click.Path(exists=True, path_type=Path),
    help="Custom config file path",
)
@click.pass_context
def cli(ctx: click.Context, config: Path | None) -> None:
    """UV-Helper: Install and manage Python scripts from Git repositories or local directories."""
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

    selected_scripts = script

    if not selected_scripts:
        from .utils import is_git_url, is_local_directory

        if not (is_local_directory(git_url) or is_git_url(git_url)):
            console.print(f"[red]Error:[/red] Invalid source: {git_url}")
            console.print("Source must be either a Git URL or a local directory path.")
            sys.exit(1)

        if not _is_interactive_terminal():
            console.print("[red]Error:[/red] --script is required in non-interactive mode.")
            console.print(
                "Use [cyan]uv-helper install <source> --script <script.py>[/cyan], "
                "or run [cyan]uv-helper browse <source>[/cyan] first."
            )
            sys.exit(1)

        try:
            candidates = _discover_install_script_candidates(git_url, config.clone_depth)
        except ValueError as e:
            console.print(f"[red]Error:[/red] Failed to discover scripts: {e}")
            sys.exit(1)

        if not candidates:
            console.print("[red]Error:[/red] No installable Python scripts found in source.")
            console.print("Try [cyan]uv-helper browse <source> --all[/cyan] to inspect all Python files.")
            sys.exit(1)

        selected_scripts = _prompt_for_script_selection(candidates)

    # Validate --alias flag usage
    if alias is not None and len(selected_scripts) != 1:
        console.print("[red]Error:[/red] --alias can only be used when installing a single script")
        sys.exit(1)

    handler = InstallHandler(config, console)

    try:
        request = _build_install_request(
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
        results = handler.install(source=git_url, scripts=selected_scripts, request=request)

        install_directory = install_dir if install_dir else config.install_dir
        display_install_results(results, install_directory, console)

        installed_scripts = [name for name, success, _ in results if success]
        if results and not installed_scripts:
            console.print("[red]Error:[/red] Installation failed for all requested scripts.")
            sys.exit(1)

        if installed_scripts:
            if len(installed_scripts) == 1:
                console.print(f"[dim]Next: uv-helper show {installed_scripts[0]} | uv-helper list[/dim]")
            else:
                console.print("[dim]Next: uv-helper list --verbose[/dim]")
    except (ValueError, FileNotFoundError, NotADirectoryError):
        sys.exit(1)


@cli.command("list")
@click.option(
    "-v",
    "--verbose",
    is_flag=True,
    help="Show detailed information (commit hash, local changes, dependencies)",
)
@click.option("--tree", is_flag=True, help="Display scripts grouped by source in a tree view")
@click.option("--full", is_flag=True, help="Disable truncation for table columns")
@click.option("--json", "json_output", is_flag=True, help="Output list as JSON")
@click.option("--source", help="Filter by source URL/path substring")
@click.option(
    "--status",
    type=click.Choice(
        ["local", "git", "pinned", "needs-attention", "clean", "managed", "unknown"],
        case_sensitive=False,
    ),
    help="Filter by script status",
)
@click.option("--ref", "ref_filter", help="Filter git refs by substring")
@click.option(
    "--sort",
    "sort_by",
    type=click.Choice(["name", "updated", "source", "status"], case_sensitive=False),
    default="name",
    show_default=True,
    help="Sort scripts by a column",
)
@click.pass_context
def list_scripts(
    ctx: click.Context,
    verbose: bool,
    tree: bool,
    full: bool,
    json_output: bool,
    source: str | None,
    status: str | None,
    ref_filter: str | None,
    sort_by: str,
) -> None:
    """
    List all installed scripts with their details.

    Displays information about installed scripts including name, status,
    source, ref, and installation date. Use --verbose for commit hash,
    local change state, and dependencies.

    Examples:

        \b
        # List all scripts in table format (default)
        uv-helper list

        \b
        # List with verbose output showing commit hash, local changes, and dependencies
        uv-helper list -v

        \b
        # Display scripts grouped by source in a tree view
        uv-helper list --tree

        \b
        # Tree view with verbose details
        uv-helper list --tree -v

        \b
        # Show full values without truncation
        uv-helper list --verbose --full

        \b
        # Filter and sort scripts
        uv-helper list --status pinned --sort updated
    """
    from rich.tree import Tree

    config = ctx.obj["config"]
    state_manager = StateManager(config.state_file)

    scripts = state_manager.list_scripts()
    scripts = _filter_and_sort_scripts(scripts, source, status, ref_filter, sort_by)

    if not scripts:
        if source or status or ref_filter:
            console.print("No scripts matched the provided filters.")
        else:
            console.print("No scripts installed.")
        return

    if json_output:
        if tree:
            console.print("[red]Error:[/red] --json cannot be combined with --tree")
            sys.exit(1)
        local_changes_cache: dict[tuple[Path, str], str] = {}
        payload = [_script_to_json(script, local_changes_cache) for script in scripts]
        click.echo(json.dumps({"scripts": payload}, indent=JSON_OUTPUT_INDENT))
        return

    if tree:
        # Group scripts by source
        groups: dict[str, list] = {}
        local_changes_by_script: dict[tuple[Path, str], str] = {}
        for script in scripts:
            key = get_script_source_display(script, shorten_git=False)

            if key not in groups:
                groups[key] = []
            groups[key].append(script)

        # Display tree
        tree_view = Tree("[bold]Installed Scripts by Source[/bold]")

        for _, source_scripts in sorted(groups.items()):
            source_node = tree_view.add(f"[magenta]{get_script_source_display(source_scripts[0])}[/magenta]")

            for script in sorted(source_scripts, key=lambda s: s.name):
                name = get_script_display_name(script, show_alias_target=True)

                if verbose:
                    # Show detailed info in verbose mode
                    details = []
                    status_key = get_script_status_key(script, local_changes_by_script)
                    status_detail = script.ref if status_key == "pinned" else None
                    details.append(f"status: {render_script_status(status_key, status_detail)}")
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
        display_scripts_table(scripts, verbose, console, full)

    _print_needs_attention_hint(scripts)


@cli.command()
@click.argument("script-name", shell_complete=complete_script_names)
@click.option("--json", "json_output", is_flag=True, help="Output details as JSON")
@click.pass_context
def show(ctx: click.Context, script_name: str, json_output: bool) -> None:
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

    if json_output:
        click.echo(json.dumps({"script": _script_to_json(script_info)}, indent=JSON_OUTPUT_INDENT))
        return

    display_script_details(script_info, console)


@cli.command()
@click.argument("script-name", shell_complete=complete_script_names)
@click.option("--clean-repo", "-c", is_flag=True, help="Remove repository if no other scripts use it")
@click.option("--force", "-f", is_flag=True, help="Skip confirmation prompt")
@click.option("--dry-run", is_flag=True, help="Preview removal without making changes")
@click.pass_context
def remove(
    ctx: click.Context,
    script_name: str,
    clean_repo: bool,
    force: bool,
    dry_run: bool,
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

        \b
        # Preview removal without applying changes
        uv-helper remove myscript --dry-run
    """
    config = ctx.obj["config"]
    state_manager = StateManager(config.state_file)

    if clean_repo:
        _print_remove_clean_repo_impact_summary(state_manager, script_name)

    script_info = state_manager.get_script_flexible(script_name)
    if dry_run:
        if script_info is None:
            console.print(f"[red]Error:[/red] Script '{script_name}' not found.")
            sys.exit(1)
        assert script_info is not None

        console.print("[bold]Dry run:[/bold] remove")
        console.print(f"  Script: {script_info.display_name}")
        console.print(f"  Source: {script_info.source_display}")
        symlink_display = str(script_info.symlink_path) if script_info.symlink_path else "Not symlinked"
        console.print(f"  Symlink: {symlink_display}")

        if clean_repo:
            scripts_from_repo = state_manager.get_scripts_from_repo(script_info.repo_path)
            if len(scripts_from_repo) == 1:
                console.print(f"  Repository action: would remove {script_info.repo_path}")
            else:
                console.print("  Repository action: kept (shared by other scripts)")

        console.print("[dim]Re-run without --dry-run to apply removal.[/dim]")
        return

    handler = RemoveHandler(config, console)

    try:
        handler.remove(script_name, clean_repo, force)
        console.print("[dim]Next: uv-helper list[/dim]")
    except (ValueError, ScriptInstallerError):
        sys.exit(1)


@cli.command()
@click.argument("script-name", required=False, shell_complete=complete_script_names)
@click.option("--all", "all_scripts", is_flag=True, help="Update all installed scripts")
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
@click.option("--dry-run", is_flag=True, help="Show what would be updated without applying changes")
@click.option("--json", "json_output", is_flag=True, help="Output update results as JSON")
@click.pass_context
def update(
    ctx: click.Context,
    script_name: str | None,
    all_scripts: bool,
    force: bool,
    exact: bool | None,
    refresh_deps: bool,
    dry_run: bool,
    json_output: bool,
) -> None:
    """
    Update installed script(s) from their configured source.

    For Git-backed scripts, fetches the latest changes and reinstalls when
    needed (or when --force is specified). For local scripts, re-copies from
    the original source path and reinstalls.

    Examples:

        \b
        # Update a script if newer version available
        uv-helper update myscript

        \b
        # Update all installed scripts
        uv-helper update --all

        \b
        # Force reinstall even if already up-to-date
        uv-helper update myscript --force

        \b
        # Update and re-resolve dependencies from requirements.txt
        uv-helper update myscript --refresh-deps

        \b
        # Preview bulk updates without changing anything
        uv-helper update --all --dry-run
    """
    if all_scripts and script_name:
        console.print("[red]Error:[/red] Cannot use SCRIPT_NAME and --all together.")
        console.print(
            "Use [cyan]uv-helper update <script-name>[/cyan] or [cyan]uv-helper update --all[/cyan]."
        )
        sys.exit(1)

    if not all_scripts and not script_name:
        console.print("[red]Error:[/red] Missing SCRIPT_NAME or --all.")
        console.print(
            "Use [cyan]uv-helper update <script-name>[/cyan] or [cyan]uv-helper update --all[/cyan]."
        )
        sys.exit(1)

    config = ctx.obj["config"]
    state_manager = StateManager(config.state_file)

    if all_scripts and not json_output:
        _print_update_all_impact_summary(state_manager, dry_run)

    handler = UpdateHandler(config, console)

    try:
        if all_scripts:
            results = handler.update_all(force, exact, refresh_deps, dry_run, show_summary=not json_output)
        else:
            assert script_name is not None
            results = [handler.update(script_name, force, exact, refresh_deps, dry_run)]

        if results:
            if json_output:
                payload = {
                    "results": _update_results_to_json(results),
                    "all": all_scripts,
                    "dry_run": dry_run,
                }
                click.echo(json.dumps(payload, indent=JSON_OUTPUT_INDENT))
                return
            else:
                display_update_results(results, console)
            if dry_run:
                console.print("[dim]Re-run without --dry-run to apply updates.[/dim]")
            elif all_scripts:
                console.print("[dim]Next: uv-helper list --verbose[/dim]")
            else:
                assert script_name is not None
                console.print(f"[dim]Next: uv-helper show {script_name}[/dim]")
    except (ValueError, FileNotFoundError, ScriptInstallerError):
        sys.exit(1)


# TODO(next-major): Remove hidden `update-all` compatibility alias.
@cli.command("update-all", hidden=True)
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
@click.option("--dry-run", is_flag=True, help="Show what would be updated without applying changes")
@click.pass_context
def update_all(
    ctx: click.Context,
    force: bool,
    exact: bool | None,
    refresh_deps: bool,
    dry_run: bool,
) -> None:
    """Compatibility alias for `update --all`."""
    ctx.invoke(
        update,
        script_name=None,
        all_scripts=True,
        force=force,
        exact=exact,
        refresh_deps=refresh_deps,
        dry_run=dry_run,
        json_output=False,
    )


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
            if script.ref_type:
                script_data["ref_type"] = script.ref_type
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

    json_output = json.dumps(export_data, indent=JSON_OUTPUT_INDENT)

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
            stored_ref_type = script_data.get("ref_type")
            alias = script_data.get("alias")

            if ref:
                ref_str = build_ref_suffix(ref, stored_ref_type)
            else:
                ref_str = ""
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
            source = f"{source}{build_ref_suffix(ref, script_data.get('ref_type'))}"

        try:
            request = _build_install_request(
                with_deps=",".join(deps) if deps else None,
                force=force,
                no_symlink=False,
                install_dir=None,
                verbose=False,
                exact=None,
                copy_parent_dir=copy_parent_dir,
                add_source_package=None,
                alias=alias,
                no_deps=False,
            )
            result = handler.install(source=source, scripts=(name,), request=request)
            results.extend(result)
        except (ValueError, FileNotFoundError, NotADirectoryError) as e:
            results.append((name, False, str(e)))

    display_install_results(results, config.install_dir, console)


@cli.command("browse")
@click.argument("git-url")
@click.option(
    "--all", "show_all", is_flag=True, help="Show all .py files including __init__.py, setup.py, etc."
)
@click.pass_context
def browse(ctx: click.Context, git_url: str, show_all: bool) -> None:
    """
    Browse available Python scripts in a Git repository.

    For GitHub repositories, tries the GitHub API first for fast listing
    without cloning. If the API is unavailable or fails, falls back to
    cloning and listing files from a local cache.

    For non-GitHub repositories, clones to local cache and lists files.

    By default, excludes common non-script files like __init__.py, setup.py,
    conftest.py, etc.

    Examples:

        \b
        # Browse scripts in a repository
        uv-helper browse https://github.com/user/repo

        \b
        # Browse a specific branch
        uv-helper browse https://github.com/user/repo#develop

        \b
        # Show all .py files including __init__.py, setup.py
        uv-helper browse https://github.com/user/repo --all
    """
    import shutil
    import subprocess

    from rich.tree import Tree

    from .git_manager import GitError, clone_or_update, parse_git_url
    from .utils import get_repo_name_from_url

    def filter_py_files(file_paths: list[str]) -> list[Path]:
        """Filter and convert file paths to Path objects."""
        py_files: list[Path] = []
        for file_path in file_paths:
            path = Path(file_path)
            if _is_install_candidate(path, show_all=show_all):
                py_files.append(path)
        return py_files

    def display_results(py_files: list[Path], repo_name: str) -> None:
        """Display the results as a tree."""
        if not py_files:
            if show_all:
                console.print("\n[yellow]No Python files found.[/yellow]")
            else:
                console.print("\n[yellow]No candidate scripts found.[/yellow]")
                console.print("[dim]Try --all to include __init__.py, setup.py, test files, etc.[/dim]")
            return

        # Group files by directory
        files_by_dir: dict[Path, list[Path]] = {}
        for py_file in sorted(py_files):
            parent = py_file.parent
            if parent not in files_by_dir:
                files_by_dir[parent] = []
            files_by_dir[parent].append(py_file)

        # Display as tree
        console.print()
        tree = Tree(f"[bold]{repo_name}[/bold]")

        for directory in sorted(files_by_dir.keys()):
            if directory == Path("."):
                dir_node = tree
            else:
                dir_node = tree.add(f"[blue]{directory}[/blue]")

            for py_file in files_by_dir[directory]:
                dir_node.add(f"[cyan]{py_file.name}[/cyan]")

        console.print(tree)
        found_label = "Python file(s)" if show_all else "candidate script(s)"
        console.print(f"\n[dim]{len(py_files)} {found_label} found[/dim]")

        # Show install hint using an installable candidate.
        installable_files = [path for path in py_files if _is_install_candidate(path, show_all=False)]
        if installable_files:
            example_script = min(installable_files, key=_install_hint_sort_key)
            console.print(f"\n[dim]Install with: uv-helper install {git_url} -s {example_script}[/dim]")
        elif show_all:
            console.print(
                "\n[dim]No candidate scripts in this list. "
                "Remove --all to focus on likely install targets.[/dim]"
            )

    def try_github_api(owner: str, repo: str, ref: str | None) -> list[str] | None:
        """Try to list .py files using GitHub API.

        Returns file paths on success. Returns None when `gh` is not installed
        or the API request fails, so the caller can fall back to clone.
        """
        # Check if gh is available
        if shutil.which("gh") is None:
            return None

        # Use ref or default to HEAD
        tree_ref = ref or "HEAD"

        try:
            result = subprocess.run(
                [
                    "gh",
                    "api",
                    f"repos/{owner}/{repo}/git/trees/{tree_ref}?recursive=1",
                    "--jq",
                    '.tree[] | select(.type == "blob" and (.path | endswith(".py"))) | .path',
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            # Each line is a .py file path
            return [line for line in result.stdout.strip().split("\n") if line]
        except subprocess.CalledProcessError:
            return None

    parsed = parse_git_url(git_url)

    console.print(f"Browsing [cyan]{parsed.base_url}[/cyan]", end="")
    if parsed.ref_value:
        console.print(f" @ [yellow]{parsed.ref_value}[/yellow]")
    else:
        console.print()

    # Check if it's a GitHub URL
    is_github = "github.com" in parsed.base_url
    repo_name = parsed.base_url.split("/")[-1]

    if is_github:
        # Extract owner/repo from URL
        # URL format: https://github.com/owner/repo
        parts = parsed.base_url.rstrip("/").split("/")
        if len(parts) >= 2:
            owner, repo = parts[-2], parts[-1]

            console.print("[dim]Fetching file list from GitHub API...[/dim]")
            files = try_github_api(owner, repo, parsed.ref_value)

            if files is not None:
                py_files = filter_py_files(files)
                display_results(py_files, repo_name)
                return

            console.print("[dim]GitHub API unavailable, falling back to clone...[/dim]")

    # Fallback: clone/update to cached directory in temp
    import tempfile

    browse_cache_dir = Path(tempfile.gettempdir()) / "uv-helper-browse"
    browse_cache_dir.mkdir(exist_ok=True)

    repo_dir_name = get_repo_name_from_url(parsed.base_url)
    repo_path = browse_cache_dir / repo_dir_name

    try:
        if repo_path.exists():
            console.print("[dim]Updating cached repository...[/dim]")
        else:
            console.print("[dim]Cloning repository...[/dim]")

        clone_or_update(
            parsed.base_url,
            parsed.ref_value,
            repo_path,
            depth=1,
            ref_type=parsed.ref_type,
        )
    except GitError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)

    # Find all .py files from cloned repo
    file_paths = [str(f.relative_to(repo_path)) for f in repo_path.rglob("*.py")]
    py_files = filter_py_files(file_paths)
    display_results(py_files, repo_name)


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
        console.print(f"{render_script_status('clean')}: No issues found - state is healthy")
    else:
        console.print(f"{render_script_status('needs-attention')} Found {len(issues)} issue(s):\n")
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

    # Script status section
    console.print("\n[bold]Script Status[/bold]")
    scripts = state_manager.list_scripts()
    if not scripts:
        console.print("[dim]No scripts installed.[/dim]")
    else:
        status_counts: dict[str, int] = {}
        local_changes_cache: dict[tuple[Path, str], str] = {}
        for script in scripts:
            status_key = get_script_status_key(script, local_changes_cache)
            status_counts[status_key] = status_counts.get(status_key, 0) + 1

        status_table = Table(show_header=False, box=None, padding=(0, 2))
        status_table.add_column("Status")
        status_table.add_column("Count", justify="right")

        for status_key in ("needs-attention", "pinned", "local", "clean", "managed", "unknown"):
            count = status_counts.get(status_key, 0)
            if count:
                status_table.add_row(render_script_status(status_key), str(count))

        console.print(status_table)

    console.print()


@cli.command("completion")
@click.argument("shell", type=click.Choice(["fish", "bash", "zsh"]))
def completion(shell: str) -> None:
    """
    Generate shell completion script.

    Outputs a completion script for the specified shell. Save this to the
    appropriate location for your shell to enable tab completion.

    Examples:

        \b
        # Fish shell
        uv-helper completion fish > ~/.config/fish/completions/uv-helper.fish

        \b
        # Bash shell
        uv-helper completion bash > ~/.local/share/bash-completion/completions/uv-helper

        \b
        # Zsh shell
        uv-helper completion zsh > ~/.zfunc/_uv-helper
        # Then add: fpath+=~/.zfunc && autoload -Uz compinit && compinit
    """
    import subprocess

    # Use click's built-in completion generation
    env_var = "_UV_HELPER_COMPLETE"
    shell_map = {
        "fish": "fish_source",
        "bash": "bash_source",
        "zsh": "zsh_source",
    }

    result = subprocess.run(
        ["uv-helper"],
        env={**dict(os.environ), env_var: shell_map[shell]},
        capture_output=True,
        text=True,
    )
    console.print(result.stdout, end="")


if __name__ == "__main__":
    cli()
