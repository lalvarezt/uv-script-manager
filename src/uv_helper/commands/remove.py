"""Remove command handler for UV-Helper."""

from rich.console import Console

from ..config import Config
from ..script_installer import ScriptInstallerError, remove_script_installation
from ..state import StateManager
from ..utils import prompt_confirm


class RemoveHandler:
    """Handles script removal logic."""

    def __init__(self, config: Config, console: Console) -> None:
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
        # Check if script exists - try by original name or symlink name
        script_info = self.state_manager.get_script_flexible(script_name)
        if not script_info:
            self.console.print(f"[red]Error:[/red] Script '{script_name}' not found.")
            raise ValueError(f"Script '{script_name}' not found")

        display_name = script_info.display_name

        # Confirm removal
        if not force:
            symlink_display = str(script_info.symlink_path) if script_info.symlink_path else "Not symlinked"
            self.console.print(f"Removing script: [cyan]{display_name}[/cyan]")
            self.console.print(f"  Source: {script_info.source_display}")
            self.console.print(f"  Symlink: {symlink_display}")

            if clean_repo:
                scripts_from_repo = self.state_manager.get_scripts_from_repo(script_info.repo_path)
                remaining = max(len(scripts_from_repo) - 1, 0)
                if remaining == 0:
                    repo_action = "will be removed"
                else:
                    repo_action = f"kept (shared by {remaining} other script(s))"
                self.console.print(f"  Repository: {script_info.repo_path} ({repo_action})")

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
