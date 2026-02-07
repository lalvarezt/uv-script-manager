"""Display functions for UV-Helper CLI output."""

import os
from pathlib import Path
from typing import cast

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from . import local_changes
from .constants import SourceType
from .state import ScriptInfo


def _normalize_status_key(status_key: str) -> str:
    """Normalize status aliases to canonical script-status keys."""
    normalized = status_key.strip().lower()
    aliases = {
        "blocking": "needs-attention",
        "needs attention": "needs-attention",
        "needs_attention": "needs-attention",
        "local-only": "local",
        "skipped (local)": "local",
        "no": "clean",
        "up-to-date": "clean",
        "no (managed)": "managed",
    }
    normalized = aliases.get(normalized, normalized)
    known = {"clean", "pinned", "local", "needs-attention", "managed", "unknown", "git"}
    return normalized if normalized in known else "unknown"


def _local_change_state_to_status_key(local_state: str) -> str:
    """Map local-change state values to canonical script-status keys."""
    normalized = local_state.strip().lower()
    if normalized in ("blocking", "needs attention", "yes"):
        return "needs-attention"
    if normalized in ("managed", "no (managed)"):
        return "managed"
    if normalized in ("clean", "no"):
        return "clean"
    return "unknown"


def get_script_status_key(script: ScriptInfo, local_changes_cache: dict[tuple[Path, str], str]) -> str:
    """Derive canonical status key used in list/show/doctor displays."""
    if script.source_type == SourceType.LOCAL:
        return "local"

    if script.ref_type in ("tag", "commit"):
        return "pinned"

    script_key = (script.repo_path, script.name)
    if script_key not in local_changes_cache:
        local_changes_cache[script_key] = local_changes.get_local_change_state(script.repo_path, script.name)

    return _local_change_state_to_status_key(local_changes_cache[script_key])


def render_script_status(status_key: str, detail: str | None = None) -> str:
    """Render a canonical script status with consistent rich styling."""
    status_key = _normalize_status_key(status_key)
    labels = {
        "clean": "[green]• Clean[/green]",
        "pinned": "[yellow]• Pinned[/yellow]",
        "local": "[dim]• Local[/dim]",
        "needs-attention": "[#ff8c00]• Needs attention[/]",
        "managed": "[green]• Managed[/green]",
        "unknown": "[dim]• Unknown[/dim]",
        "git": "[cyan]• Git[/cyan]",
    }
    rendered = labels[status_key]
    if detail:
        return f"{rendered} [dim]({detail})[/dim]"
    return rendered


def _render_local_changes_state(local_state: str) -> str:
    """Render local change state with consistent labels and styles."""
    if local_state in ("N/A", "n/a"):
        return "[dim]N/A[/dim]"
    status_key = _local_change_state_to_status_key(local_state)
    if status_key == "unknown":
        return "[dim]• Unknown[/dim]"
    if status_key == "managed":
        return render_script_status("managed")
    if status_key == "clean":
        return render_script_status("clean")
    if status_key == "needs-attention":
        return render_script_status("needs-attention")
    return "[dim]• Unknown[/dim]"


def _get_list_column_max_widths(console: Console, verbose: bool, full: bool) -> dict[str, int | None]:
    """Return adaptive max widths for list table columns."""
    keys = ("script", "status", "source", "ref", "updated", "commit", "local_changes", "dependencies")
    if full:
        return {key: None for key in keys}

    width = max(console.width, 80)
    if verbose:
        return {
            "script": max(16, min(30, width // 6)),
            "status": max(14, min(20, width // 8)),
            "source": max(18, min(36, width // 4)),
            "ref": max(8, min(16, width // 10)),
            "updated": 16,
            "commit": max(8, min(12, width // 11)),
            "local_changes": max(14, min(20, width // 7)),
            "dependencies": max(16, min(36, width // 4)),
        }

    return {
        "script": max(16, min(34, width // 4)),
        "status": max(14, min(20, width // 8)),
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
        "Status",
        max_width=widths["status"],
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

        status_key = get_script_status_key(script, local_changes_by_script)
        status_detail = script.ref if status_key == "pinned" else None
        status_display = render_script_status(status_key, status_detail)

        row = [
            script_display,
            status_display,
            source_display,
            ref_display,
            script.installed_at.strftime("%Y-%m-%d %H:%M"),
        ]

        if verbose:
            commit_display = script.commit_hash if script.commit_hash else "N/A"
            if script.source_type == SourceType.GIT:
                script_key = (script.repo_path, script.name)
                if script_key not in local_changes_by_script:
                    local_changes_by_script[script_key] = local_changes.get_local_change_state(
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
            status_text = render_script_status("clean")
        elif status == "would update":
            status_text = "[cyan]• Update available[/cyan]"
        elif status in (
            "would update (local custom changes present)",
            "would update (local changes present)",
        ):
            status_text = render_script_status("needs-attention")
        elif status == "skipped (local)":
            status_text = render_script_status("local")
        elif status.startswith("pinned to "):
            status_text = render_script_status("pinned", status.removeprefix("pinned to "))
        elif status.startswith("Error:"):
            status_text = f"[red]✗ {status}[/red]"
        else:
            status_text = f"[yellow]• {status}[/yellow]"

        local_changes_text = _render_local_changes_state(local_changes)

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

    status_cache: dict[tuple[Path, str], str] = {}
    status_key = get_script_status_key(script, status_cache)
    status_detail = script.ref if status_key == "pinned" else None
    table.add_row("Status:", render_script_status(status_key, status_detail))

    # Source info
    if script.source_type == SourceType.GIT:
        table.add_row("Source type:", "Git repository")
        table.add_row("Source URL:", f"[magenta]{script.source_url}[/magenta]")
        table.add_row("Ref:", f"[green]{script.ref or 'default'}[/green]")
        table.add_row("Commit:", f"[blue]{script.commit_hash or 'N/A'}[/blue]")
        local_state = local_changes.get_local_change_state(script.repo_path, script.name)
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
