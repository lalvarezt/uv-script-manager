"""Remove command handler for UV-Helper."""

from rich.console import Console

from ..config import Config
from ..constants import SourceType
from ..script_installer import ScriptInstallerError, remove_script_installation
from ..state import StateManager
from ..utils import prompt_confirm


class RemoveHandler:
    """Handles script removal logic."""

    def __init__(self, config: Config, console: Console):
        """
        Initialize remove handler.

        Args:
            config: Application configuration
            console: Rich console for output
        """
        self.config = config
        self.console = console
        self.state_manager = StateManager(config.state_file)

    def remove(self, script_name: str, clean_repo: bool, force: bool) -> None:
        """
        Remove an installed script.

        Args:
            script_name: Name of script to remove (can be original name or alias)
            clean_repo: Remove repository if no other scripts use it
            force: Skip confirmation prompt

        Raises:
            ValueError: If script not found
            ScriptInstallerError: If removal fails
        """
        # Check if script exists - try by original name first, then by symlink name
        script_info = self.state_manager.get_script(script_name)
        if not script_info:
            # Try searching by symlink name (alias)
            script_info = self.state_manager.get_script_by_symlink(script_name)

        if not script_info:
            self.console.print(f"[red]Error:[/red] Script '{script_name}' not found.")
            raise ValueError(f"Script '{script_name}' not found")

        # Determine display name (use symlink name if available)
        if script_info.symlink_path:
            display_name = script_info.symlink_path.name
        else:
            display_name = script_info.name

        # Confirm removal
        if not force:
            self.console.print(f"Removing script: [cyan]{display_name}[/cyan]")

            if script_info.source_type == SourceType.GIT:
                source_display = script_info.source_url or "N/A"
            else:
                source_display = (
                    str(script_info.source_path) if script_info.source_path else "local"
                )

            self.console.print(f"  Source: {source_display}")
            self.console.print(f"  Symlink: {script_info.symlink_path}")

            if clean_repo:
                self.console.print(f"  Repository: {script_info.repo_path} (will be removed)")

            if not prompt_confirm("Proceed with removal?", default=False):
                self.console.print("Removal cancelled.")
                return

        # Remove script (use actual script name from state, not user input)
        try:
            remove_script_installation(script_info.name, self.state_manager, clean_repo=clean_repo)
            self.console.print(f"[green]✓[/green] Successfully removed {display_name}")
        except ScriptInstallerError as e:
            self.console.print(f"[red]Error:[/red] {e}")
            raise
