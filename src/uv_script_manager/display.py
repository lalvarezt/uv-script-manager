"""Display functions for CLI output."""

import os
from pathlib import Path
from typing import cast

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from . import local_changes
from .constants import SourceType
from .state import ScriptInfo
from .update_status import (
    UPDATE_STATUS_SKIPPED_LOCAL,
    UPDATE_STATUS_UP_TO_DATE,
    UPDATE_STATUS_UPDATED,
    UPDATE_STATUS_WOULD_UPDATE,
    UPDATE_STATUS_WOULD_UPDATE_LOCAL_CHANGES,
    UPDATE_STATUS_WOULD_UPDATE_LOCAL_CHANGES_LEGACY,
    is_error_status,
    parse_pinned_status,
)


def _normalize_status_key(status_key: str) -> str:
    """Normalize status aliases to canonical script-status keys."""
    normalized = status_key.strip().lower()
    aliases = {
        "blocking": "needs-attention",
        "needs attention": "needs-attention",
        "needs_attention": "needs-attention",
        "local-only": "local",
        UPDATE_STATUS_SKIPPED_LOCAL: "local",
        "no": "clean",
        UPDATE_STATUS_UP_TO_DATE: "clean",
        "no (managed)": "managed",
    }
    normalized = aliases.get(normalized, normalized)
    known = {"clean", "pinned", "local", "needs-attention", "managed", "unknown", "git"}
    return normalized if normalized in known else "unknown"


def _local_change_state_to_status_key(local_state: str) -> str:
    """Map local-change state values to canonical script-status keys."""
    normalized = local_state.strip().lower()
    if normalized in ("blocking", "needs attention", "needs-attention", "yes"):
        return "needs-attention"
    if normalized in ("managed", "no (managed)"):
        return "managed"
    if normalized in ("clean", "no"):
        return "clean"
    return "unknown"


def format_local_change_label(local_state: str) -> str:
    """Format local-change state into legacy update-table labels."""
    status_key = _local_change_state_to_status_key(local_state)
    if status_key == "needs-attention":
        return "Needs attention"
    if status_key == "managed":
        return "No (managed)"
    if status_key == "clean":
        return "No"
    return "Unknown"


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


def get_script_display_name(script: ScriptInfo, show_alias_target: bool = False) -> str:
    """Return script display name, optionally showing alias relationship."""
    if script.symlink_path:
        symlink_name = script.symlink_path.name
        if show_alias_target and symlink_name != script.name:
            return f"{symlink_name} -> {script.name}"
        return symlink_name
    return script.name


def get_script_source_display(
    script: ScriptInfo,
    *,
    shorten_git: bool = True,
    missing_git: str = "unknown",
) -> str:
    """Return source display string for script list/show outputs."""
    if script.source_type == SourceType.GIT:
        if not script.source_url:
            return missing_git
        if not shorten_git:
            return script.source_url
        source_parts = script.source_url.rstrip("/").split("/")
        return "/".join(source_parts[-2:]) if len(source_parts) >= 2 else script.source_url
    return str(script.source_path) if script.source_path else "local"


def render_script_status(status_key: str, detail: str | None = None) -> str:
    """Render a canonical script status with consistent rich styling."""
    status_key = _normalize_status_key(status_key)
    labels = {
        "clean": "[green]Clean[/green]",
        "pinned": "[yellow]Pinned[/yellow]",
        "local": "[dim]Local[/dim]",
        "needs-attention": "[#ff8c00]Needs attention[/]",
        "managed": "[green]Managed[/green]",
        "unknown": "[dim]Unknown[/dim]",
        "git": "[cyan]Git[/cyan]",
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
    if status_key in ("managed", "clean", "needs-attention"):
        return render_script_status(status_key)

    return "[dim]Unknown[/dim]"


def _get_list_column_max_widths(console: Console, verbose: bool, full: bool) -> dict[str, int | None]:
    """Return adaptive max widths for list table columns."""
    keys = ("script", "status", "source", "ref", "updated", "commit", "local_changes", "dependencies")
    if full:
        return {key: None for key in keys}

    width = max(console.width, 80)
    if verbose:
        return {
            "script": max(16, min(26, width // 7)),
            "status": max(16, min(22, width // 7)),
            "source": max(16, min(26, width // 7)),
            "ref": max(10, min(18, width // 9)),
            "updated": 16,
            "commit": max(8, min(10, width // 14)),
            "local_changes": max(12, min(16, width // 9)),
            "dependencies": max(12, min(18, width // 8)),
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
    table.add_column("Status")
    table.add_column("Location")

    for script_name, success, location in results:
        if success:
            status = "[green]✓ Installed[/green]"
            loc = str(location) if location else "[dim]Not symlinked[/dim]"
        else:
            status = "[red]✗ Failed[/red]"
            loc = str(location) if location else "[dim]Unknown error[/dim]"

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
        full: Whether to disable column truncation
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
        min_width=10,
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
        min_width=8,
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
        script_display = get_script_display_name(script, show_alias_target=verbose)
        source_display = get_script_source_display(script, shorten_git=True, missing_git="N/A")
        if script.source_type == SourceType.GIT:
            ref_display = script.ref or "N/A"
        else:
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
                local_state = local_changes_by_script.get(script_key)
                if local_state is None:
                    local_state = local_changes.get_local_change_state(script.repo_path, script.name)
                    local_changes_by_script[script_key] = local_state
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
        results: List of tuples (script_name, status) or
            (script_name, status, local_changes)
        console: Rich console instance for output
    """
    table = Table(title="Update Results")
    table.add_column("Script", style="cyan")
    table.add_column("Status")

    show_local_changes = any(
        len(result) == 3 and cast(tuple[str, str, str], result)[2].strip().lower() != "n/a"
        for result in results
    )
    if show_local_changes:
        table.add_column("Local changes")

    for result in results:
        if len(result) == 3:
            script_name, status, local_changes = cast(tuple[str, str, str], result)
        else:
            script_name, status = cast(tuple[str, str], result)
            local_changes = "N/A"

        status_text = render_update_status(status)

        local_changes_text = _render_local_changes_state(local_changes)

        if show_local_changes:
            table.add_row(script_name, status_text, local_changes_text)
        else:
            table.add_row(script_name, status_text)

    console.print(table)


def render_update_status(status: str) -> str:
    """Render an update status with update-specific labels and styles."""
    if status == UPDATE_STATUS_UPDATED:
        return "[green]✓ Updated[/green]"
    if status == UPDATE_STATUS_UP_TO_DATE:
        return "[green]Up to date[/green]"
    if status == UPDATE_STATUS_WOULD_UPDATE:
        return "[cyan]Update available[/cyan]"
    if status in (
        UPDATE_STATUS_WOULD_UPDATE_LOCAL_CHANGES,
        UPDATE_STATUS_WOULD_UPDATE_LOCAL_CHANGES_LEGACY,
    ):
        return render_script_status("needs-attention")
    if status == UPDATE_STATUS_SKIPPED_LOCAL:
        return "[dim]Skipped (local-only)[/dim]"
    if (pinned_ref := parse_pinned_status(status)) is not None:
        return render_script_status("pinned", pinned_ref)
    if is_error_status(status):
        return f"[red]✗ {status}[/red]"
    return f"[yellow]{status}[/yellow]"


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
    status_rows: list[tuple[str, str]] = []

    # Source info
    if script.source_type == SourceType.GIT:
        table.add_row("Source type:", "Git repository")
        table.add_row("Source URL:", f"[magenta]{script.source_url}[/magenta]")
        table.add_row("Ref:", f"[green]{script.ref or 'default'}[/green]")
        table.add_row("Commit:", f"[blue]{script.commit_hash or 'N/A'}[/blue]")
        table.add_row("", "")
        local_state = local_changes.get_local_change_state(script.repo_path, script.name)
        change_reason = local_changes.get_local_change_details(script.repo_path, script.name)
        if change_reason:
            status_rows.append(("Reason:", change_reason))
        if local_state in ("blocking", "unknown") and script.repo_path.exists():
            status_rows.append(("Inspect with:", f"[cyan]git -C {script.repo_path} status --short[/cyan]"))
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

    table.add_row("", "")
    table.add_row("Status:", render_script_status(status_key, status_detail))
    for label, value in status_rows:
        table.add_row(label, value)

    title = f"Script: {script.display_name}"
    console.print(Panel(table, title=title, border_style="cyan"))
