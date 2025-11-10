"""Display functions for UV-Helper CLI output."""

import os
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .constants import SourceType
from .state import ScriptInfo


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
) -> None:
    """
    Display installed scripts in a table.

    Args:
        scripts: List of ScriptInfo instances
        verbose: Whether to show detailed information
        console: Rich console instance for output
    """
    table = Table(title="Installed Scripts")
    table.add_column("Script", style="cyan")
    table.add_column("Source", style="magenta")
    table.add_column("Ref", style="green")
    table.add_column("Installed", style="yellow")

    if verbose:
        table.add_column("Commit", style="blue")
        table.add_column("Dependencies")

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
            source_display = (
                script.source_url.split("/")[-2:][0] + "/" + script.source_url.split("/")[-1]
            )
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
            row.append(commit_display)
            row.append(", ".join(script.dependencies) if script.dependencies else "None")

        table.add_row(*row)

    console.print(table)


def display_update_results(
    results: list[tuple[str, str]],
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

    for script_name, status in results:
        if status == "updated":
            status_text = "[green]✓ Updated[/green]"
        elif status == "up-to-date":
            status_text = "[blue]✓ Up-to-date[/blue]"
        else:
            status_text = f"[red]✗ {status}[/red]"

        table.add_row(script_name, status_text)

    console.print(table)
