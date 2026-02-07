"""Display functions for UV-Helper CLI output."""

import os
from pathlib import Path
from typing import cast

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .constants import SourceType
from .local_changes import get_local_change_state
from .state import ScriptInfo


def _render_local_changes_state(local_state: str) -> str:
    """Render local change state with consistent labels and styles."""
    if local_state in ("blocking", "Needs attention", "Yes"):
        return "[#ff8c00]Needs attention[/]"
    if local_state in ("managed", "No (managed)"):
        return "[green]No (managed)[/green]"
    if local_state in ("clean", "No"):
        return "[green]No[/green]"
    if local_state in ("N/A", "n/a"):
        return "[dim]N/A[/dim]"
    return "[dim]Unknown[/dim]"


def _get_list_column_max_widths(console: Console, verbose: bool, full: bool) -> dict[str, int | None]:
    """Return adaptive max widths for list table columns."""
    keys = ("script", "source", "ref", "updated", "commit", "local_changes", "dependencies")
    if full:
        return {key: None for key in keys}

    width = max(console.width, 80)
    if verbose:
        return {
            "script": max(16, min(30, width // 6)),
            "source": max(18, min(36, width // 4)),
            "ref": max(8, min(16, width // 10)),
            "updated": 16,
            "commit": max(8, min(12, width // 11)),
            "local_changes": max(14, min(20, width // 7)),
            "dependencies": max(16, min(36, width // 4)),
        }

    return {
        "script": max(16, min(34, width // 4)),
        "source": max(18, min(44, width // 3)),
        "ref": max(8, min(18, width // 8)),
        "updated": 16,
        "commit": None,
        "local_changes": None,
        "dependencies": None,
    }


def display_install_results(
    results: list[tuple[str, bool, Path | None | str]],
    install_dir: Path,
    console: Console,
) -> None:
    """
    Display installation results in a table.

    Args:
        results: List of tuples (script_name, success, location_or_error)
        install_dir: Installation directory path
        console: Rich console instance for output
    """
    table = Table(title="Installation Results")
    table.add_column("Script", style="cyan")
    table.add_column("Status", style="green")
    table.add_column("Location")

    for script_name, success, location in results:
        if success:
            status = "✓ Installed"
            loc = str(location) if location else "N/A"
        else:
            status = "✗ Failed"
            loc = str(location)

        table.add_row(script_name, status, loc)

    console.print(table)

    # Check if install_dir is in PATH
    if str(install_dir) not in os.environ.get("PATH", ""):
        console.print(
            Panel(
                f"[yellow]Warning:[/yellow] {install_dir} is not in your PATH.\n"
                f"Add it to your shell configuration:\n"
                f'  export PATH="{install_dir}:$PATH"',
                title="PATH Warning",
                border_style="yellow",
            )
        )


def display_scripts_table(
    scripts: list[ScriptInfo],
    verbose: bool,
    console: Console,
    full: bool = False,
) -> None:
    """
    Display installed scripts in a table.

    Args:
        scripts: List of ScriptInfo instances
        verbose: Whether to show detailed information
        console: Rich console instance for output
    """
    widths = _get_list_column_max_widths(console, verbose, full)
    overflow = "fold" if full else "ellipsis"

    table = Table(title="Installed Scripts")
    table.add_column(
        "Script",
        style="cyan",
        max_width=widths["script"],
        overflow=overflow,
        no_wrap=not full,
    )
    table.add_column(
        "Source",
        style="magenta",
        max_width=widths["source"],
        overflow=overflow,
        no_wrap=not full,
    )
    table.add_column(
        "Ref",
        style="green",
        max_width=widths["ref"],
        overflow=overflow,
        no_wrap=not full,
    )
    table.add_column(
        "Updated",
        style="yellow",
        max_width=widths["updated"],
        overflow=overflow,
        no_wrap=True,
    )

    if verbose:
        table.add_column(
            "Commit",
            style="blue",
            max_width=widths["commit"],
            overflow=overflow,
            no_wrap=not full,
        )
        table.add_column(
            "Local changes",
            max_width=widths["local_changes"],
            overflow=overflow,
            no_wrap=not full,
        )
        table.add_column(
            "Dependencies",
            max_width=widths["dependencies"],
            overflow=overflow,
            no_wrap=not full,
        )

    local_changes_by_script: dict[tuple[Path, str], str] = {}

    for script in scripts:
        # Determine the display name (use symlink name if available, otherwise script name)
        if script.symlink_path:
            symlink_name = script.symlink_path.name
            script_display = symlink_name
            # In verbose mode, show relationship if names differ
            if verbose and symlink_name != script.name:
                script_display = f"{symlink_name} -> {script.name}"
        else:
            script_display = script.name

        # Display source based on type
        if script.source_type == SourceType.GIT and script.source_url:
            source_parts = script.source_url.rstrip("/").split("/")
            source_display = "/".join(source_parts[-2:]) if len(source_parts) >= 2 else script.source_url
            ref_display = script.ref or "N/A"
        else:
            # Local source
            source_display = str(script.source_path) if script.source_path else "local"
            ref_display = "N/A"

        row = [
            script_display,
            source_display,
            ref_display,
            script.installed_at.strftime("%Y-%m-%d %H:%M"),
        ]

        if verbose:
            commit_display = script.commit_hash if script.commit_hash else "N/A"
            if script.source_type == SourceType.GIT:
                script_key = (script.repo_path, script.name)
                if script_key not in local_changes_by_script:
                    local_changes_by_script[script_key] = get_local_change_state(
                        script.repo_path, script.name
                    )
                local_state = local_changes_by_script[script_key]
                local_changes_display = _render_local_changes_state(local_state)
            else:
                local_changes_display = _render_local_changes_state("N/A")

            row.append(commit_display)
            row.append(local_changes_display)
            row.append(", ".join(script.dependencies) if script.dependencies else "None")

        table.add_row(*row)

    console.print(table)


def display_update_results(
    results: list[tuple[str, str] | tuple[str, str, str]],
    console: Console,
) -> None:
    """
    Display update results in a table.

    Args:
        results: List of tuples (script_name, status_message)
        console: Rich console instance for output
    """
    table = Table(title="Update Results")
    table.add_column("Script", style="cyan")
    table.add_column("Status", style="green")

    show_local_changes = any(len(result) == 3 for result in results)
    if show_local_changes:
        table.add_column("Local changes")

    for result in results:
        if len(result) == 3:
            script_name, status, local_changes = cast(tuple[str, str, str], result)
        else:
            script_name, status = cast(tuple[str, str], result)
            local_changes = "N/A"

        if status == "updated":
            status_text = "[green]✓ Updated[/green]"
        elif status == "up-to-date":
            status_text = "[blue]✓ Up-to-date[/blue]"
        elif status == "would update":
            status_text = "[cyan]• Update available[/cyan]"
        elif status in (
            "would update (local custom changes present)",
            "would update (local changes present)",
        ):
            status_text = "[#ff8c00]• Needs attention (local changes)[/]"
        elif status == "skipped (local)":
            status_text = "[dim]• Local-only[/dim]"
        elif status.startswith("pinned to "):
            status_text = f"[yellow]• Pinned ({status.removeprefix('pinned to ')})[/yellow]"
        elif status.startswith("Error:"):
            status_text = f"[red]✗ {status}[/red]"
        else:
            status_text = f"[yellow]• {status}[/yellow]"

        if local_changes in ("Needs attention", "Yes"):
            local_changes_text = "[#ff8c00]Needs attention[/]"
        elif local_changes in ("No", "No (managed)"):
            local_changes_text = f"[green]{local_changes}[/green]"
        elif local_changes in ("Unknown", "N/A"):
            local_changes_text = f"[dim]{local_changes}[/dim]"
        else:
            local_changes_text = local_changes

        if show_local_changes:
            table.add_row(script_name, status_text, local_changes_text)
        else:
            table.add_row(script_name, status_text)

    console.print(table)


def display_script_details(script: ScriptInfo, console: Console) -> None:
    """
    Display detailed information about a single script.

    Args:
        script: ScriptInfo instance
        console: Rich console instance for output
    """
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Label", style="dim")
    table.add_column("Value")

    # Basic info
    table.add_row("Name:", f"[cyan]{script.name}[/cyan]")

    if script.symlink_path and script.symlink_path.name != script.name:
        table.add_row("Alias:", f"[cyan]{script.symlink_path.name}[/cyan]")

    # Source info
    if script.source_type == SourceType.GIT:
        table.add_row("Source type:", "Git repository")
        table.add_row("Source URL:", f"[magenta]{script.source_url}[/magenta]")
        table.add_row("Ref:", f"[green]{script.ref or 'default'}[/green]")
        table.add_row("Commit:", f"[blue]{script.commit_hash or 'N/A'}[/blue]")
        local_state = get_local_change_state(script.repo_path, script.name)
        local_changes_display = _render_local_changes_state(local_state)
        table.add_row("Local changes:", local_changes_display)
    else:
        table.add_row("Source type:", "Local directory")
        source_path = str(script.source_path) if script.source_path else "N/A"
        table.add_row("Source path:", f"[magenta]{source_path}[/magenta]")
        if script.copy_parent_dir:
            table.add_row("Copy mode:", "Entire directory")

    # Paths
    table.add_row("Script path:", str(script.repo_path / script.name))
    if script.symlink_path:
        table.add_row("Symlink:", str(script.symlink_path))

    # Installation info
    table.add_row("Installed:", script.installed_at.strftime("%Y-%m-%d %H:%M:%S"))

    # Dependencies
    if script.dependencies:
        deps_str = ", ".join(script.dependencies)
        table.add_row("Dependencies:", deps_str)
    else:
        table.add_row("Dependencies:", "[dim]None[/dim]")

    title = f"Script: {script.display_name}"
    console.print(Panel(table, title=title, border_style="cyan"))
