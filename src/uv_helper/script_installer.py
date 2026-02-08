"""Script installation and processing for UV-Helper."""

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from pathvalidate import ValidationError, validate_filename

from .constants import (
    SCRIPT_METADATA_END,
    SCRIPT_METADATA_SOURCES_SECTION,
    SCRIPT_METADATA_START,
    SCRIPT_VERIFICATION_TIMEOUT,
    SHEBANG_UV_RUN,
    SHEBANG_UV_RUN_EXACT,
)
from .state import StateManager
from .utils import run_command, safe_rmtree, validate_python_script


class ScriptInstallerError(Exception):
    """
    Raised when script installation or processing fails.

    This exception is raised for various script-related failures including:
    - Invalid Python script files
    - Failed dependency installation (uv add --script failures)
    - Shebang modification failures (file I/O errors)
    - Symlink creation failures (permission issues, filesystem limitations)
    - Script execution permission failures (chmod errors)
    - Script removal failures (missing scripts, file system errors)
    - UV not available in PATH

    The error message provides specific details about the failure.
    """

    pass


@dataclass
class InstallConfig:
    """Configuration for script installation.

    Groups installation-related parameters to reduce parameter count in install_script().
    All fields have sensible defaults matching current behavior.
    """

    install_dir: Path
    auto_chmod: bool = True
    auto_symlink: bool = True
    verify_after_install: bool = True
    use_exact: bool = True
    script_alias: str | None = None


def process_script_dependencies(script_path: Path, dependencies: list[str]) -> bool:
    """
    Add dependencies to script using uv add --script.

    Args:
        script_path: Path to Python script
        dependencies: List of dependencies to add

    Returns:
        True if successful

    Raises:
        ScriptInstallerError: If adding dependencies fails
    """
    if not dependencies:
        return True

    try:
        # Build uv add --script command
        cmd = ["uv", "add", "--script", str(script_path)]
        cmd.extend(dependencies)

        run_command(cmd, check=True)
        return True
    except subprocess.CalledProcessError as e:
        raise ScriptInstallerError(f"Failed to add dependencies to script: {e.stderr}") from e


def modify_shebang(script_path: Path, use_exact: bool = True) -> None:
    """
    Modify script shebang to use uv run --script.

    Transforms:
        #!/usr/bin/env python3
    To:
        #!/usr/bin/env -S uv run --exact --script (if use_exact=True)
        #!/usr/bin/env -S uv run --script (if use_exact=False)

    Args:
        script_path: Path to Python script
        use_exact: Whether to include --exact flag for precise dependency management

    Raises:
        ScriptInstallerError: If modification fails
    """
    try:
        with open(script_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        if not lines:
            raise ScriptInstallerError("Script file is empty")

        # Use shebang constant based on use_exact flag
        shebang = SHEBANG_UV_RUN_EXACT if use_exact else SHEBANG_UV_RUN

        # Check if first line is a shebang
        if lines[0].startswith("#!"):
            # Replace with uv shebang
            lines[0] = shebang
        else:
            # Add shebang at the beginning
            lines.insert(0, shebang)

        # Write back
        with open(script_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
    except (OSError, UnicodeDecodeError) as e:
        raise ScriptInstallerError(f"Failed to modify shebang: {e}") from e


def add_package_source(script_path: Path, package_name: str, package_path: Path) -> bool:
    """
    Add a package source to script's inline metadata.

    Adds or updates the [tool.uv.sources] section in the script's inline
    metadata block with an absolute path to prevent UV from creating relative paths.

    Args:
        script_path: Path to Python script
        package_name: Name of the package
        package_path: Absolute path to the package directory

    Returns:
        True if successful

    Raises:
        ScriptInstallerError: If modification fails
    """
    try:
        with open(script_path, "r", encoding="utf-8") as f:
            content = f.read()

        lines = content.splitlines(keepends=True)

        # Find the script metadata block
        start_idx = None
        end_idx = None
        for i, line in enumerate(lines):
            if line.strip() == SCRIPT_METADATA_START:
                start_idx = i
            elif start_idx is not None and line.strip() == SCRIPT_METADATA_END:
                end_idx = i
                break

        # Resolve to absolute path
        abs_package_path = package_path.resolve()

        # Prepare the source line
        source_line = f'# {package_name} = {{ path = "{abs_package_path}" }}\n'

        if start_idx is not None and end_idx is not None:
            # Metadata block exists, check if [tool.uv.sources] section exists
            sources_idx = None
            for i in range(start_idx + 1, end_idx):
                if lines[i].strip() == SCRIPT_METADATA_SOURCES_SECTION:
                    sources_idx = i
                    break

            if sources_idx is not None:
                # [tool.uv.sources] exists, check if package already defined
                package_idx = None
                for i in range(sources_idx + 1, end_idx):
                    if lines[i].strip().startswith(f"# {package_name} ="):
                        package_idx = i
                        break

                if package_idx is not None:
                    # Update existing package line
                    lines[package_idx] = source_line
                else:
                    # Add new package after [tool.uv.sources]
                    lines.insert(sources_idx + 1, source_line)
            else:
                # Add [tool.uv.sources] section before closing ///
                lines.insert(end_idx, f"{SCRIPT_METADATA_SOURCES_SECTION}\n")
                lines.insert(end_idx + 1, source_line)
        else:
            # No metadata block exists, create one after shebang
            shebang_idx = 0
            if lines and lines[0].startswith("#!"):
                shebang_idx = 1

            metadata_lines = [
                f"{SCRIPT_METADATA_START}\n",
                f"{SCRIPT_METADATA_SOURCES_SECTION}\n",
                source_line,
                f"{SCRIPT_METADATA_END}\n",
            ]

            # Insert after shebang (if exists) or at the beginning
            for line in reversed(metadata_lines):
                lines.insert(shebang_idx, line)

        # Write back
        with open(script_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
        return True
    except (OSError, UnicodeDecodeError) as e:
        raise ScriptInstallerError(f"Failed to add package source: {e}") from e


def check_shadows_system_command(name: str, target_dir: Path) -> str | None:
    """
    Check if a symlink name would shadow a system command.

    Args:
        name: The symlink name to check
        target_dir: The directory where the symlink will be created

    Returns:
        Path to existing system command if shadowing would occur, None otherwise
    """
    # First check if there's already a command with this name
    existing_path = shutil.which(name)
    if existing_path is None:
        return None

    # Don't warn if the existing command is in our target directory
    # (would be a previous installation we're overwriting)
    existing = Path(existing_path)
    if existing.parent == target_dir:
        return None

    return existing_path


def create_symlink(
    script_path: Path,
    target_dir: Path,
    script_name: str | None = None,
) -> tuple[Path, str | None]:
    """
    Create symlink to script in target directory.

    Args:
        script_path: Path to script file
        target_dir: Directory to create symlink in
        script_name: Optional custom name for symlink (default: script filename)

    Returns:
        Tuple of (path to created symlink, warning message if shadowing system command)

    Raises:
        ScriptInstallerError: If symlink creation fails
    """
    try:
        # Ensure target directory exists
        target_dir.mkdir(parents=True, exist_ok=True)

        # Determine symlink name
        if script_name is None:
            script_name = script_path.name

        # Validate symlink name to prevent path traversal
        try:
            validate_filename(script_name, platform="auto")
        except ValidationError as e:
            raise ScriptInstallerError(f"Invalid symlink name '{script_name}': {e}") from e

        # Check for system command shadowing
        shadow_warning = None
        shadowed_path = check_shadows_system_command(script_name, target_dir)
        if shadowed_path:
            shadow_warning = f"'{script_name}' shadows existing command at {shadowed_path}"

        symlink_path = target_dir / script_name

        # Fix TOCTOU race condition: Remove any existing file/symlink atomically
        # Use missing_ok=True to avoid race if file disappears between check and unlink
        # Try to create symlink first, handle FileExistsError if it occurs
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                # Attempt atomic symlink creation
                symlink_path.symlink_to(script_path)
                return symlink_path, shadow_warning
            except FileExistsError:
                # Something exists at this path - remove it and retry
                try:
                    # Use missing_ok to handle concurrent deletion
                    symlink_path.unlink(missing_ok=True)
                except (OSError, RuntimeError) as unlink_err:
                    # If unlink fails and this is the last attempt, raise
                    if attempt == max_attempts - 1:
                        raise ScriptInstallerError(
                            f"Failed to remove existing file at {symlink_path}"
                        ) from unlink_err
                # Retry symlink creation
                continue

        # If we exit the loop without returning, raise an error
        raise ScriptInstallerError(
            f"Failed to create symlink at {symlink_path} after {max_attempts} attempts"
        )

    except OSError as e:
        raise ScriptInstallerError(f"Failed to create symlink: {e}") from e


def make_executable(script_path: Path) -> None:
    """
    Make script executable.

    Args:
        script_path: Path to script file

    Raises:
        ScriptInstallerError: If chmod fails
    """
    try:
        # Add execute permission for owner only (security best practice)
        current_mode = script_path.stat().st_mode
        script_path.chmod(current_mode | 0o100)  # Add execute for user only
    except OSError as e:
        raise ScriptInstallerError(f"Failed to make script executable: {e}") from e


def verify_script(script_path: Path) -> bool:
    """
    Verify that script can be executed.

    Tries to run script with --help flag with a timeout
    to prevent hanging on malicious or broken scripts.

    Args:
        script_path: Path to script

    Returns:
        True if script runs successfully, False otherwise
    """
    try:
        # Try running with --help with timeout for security
        result = run_command(
            [str(script_path), "--help"],
            capture_output=True,
            check=False,
            timeout=SCRIPT_VERIFICATION_TIMEOUT,
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        # Script timed out
        return False
    except (subprocess.CalledProcessError, OSError, FileNotFoundError):
        # Script failed to run or doesn't exist
        return False


def remove_script_installation(
    script_name: str,
    state_manager: StateManager,
    clean_repo: bool = False,
) -> None:
    """
    Remove an installed script.

    Args:
        script_name: Name of script to remove
        state_manager: StateManager instance
        clean_repo: Whether to clean up repository if no other scripts use it

    Raises:
        ScriptInstallerError: If removal fails
    """
    script_info = state_manager.get_script(script_name)
    if not script_info:
        raise ScriptInstallerError(f"Script '{script_name}' not found in state")

    try:
        # Remove symlink if exists
        if script_info.symlink_path and script_info.symlink_path.exists():
            script_info.symlink_path.unlink()

        # Clean up repository if requested
        if clean_repo:
            scripts_from_repo = state_manager.get_scripts_from_repo(script_info.repo_path)

            # Only delete repo if this is the last script from it
            if len(scripts_from_repo) == 1:
                if script_info.repo_path.exists():
                    safe_rmtree(script_info.repo_path)

        # Remove from state
        state_manager.remove_script(script_name)
    except OSError as e:
        raise ScriptInstallerError(f"Failed to remove script: {e}") from e


def verify_uv_available() -> None:
    """
    Verify that uv command is available.

    Raises:
        ScriptInstallerError: If uv is not available
    """
    try:
        run_command(["uv", "--version"], check=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        raise ScriptInstallerError("UV is not installed or not in PATH") from e


def install_script(
    script_path: Path,
    dependencies: list[str],
    config: InstallConfig,
) -> tuple[Path | None, str | None]:
    """
    Install a script with all processing steps.

    Steps:
    1. Validate script
    2. Add dependencies
    3. Modify shebang
    4. Make executable
    5. Create symlink
    6. Verify

    Args:
        script_path: Path to script file
        dependencies: List of dependencies
        config: Installation configuration (install_dir, flags, etc.)

    Returns:
        Tuple of (path to symlink if created, warning message if any)

    Raises:
        ScriptInstallerError: If installation fails
    """
    # Validate script
    if not validate_python_script(script_path):
        raise ScriptInstallerError(f"Invalid Python script: {script_path}")

    # Add dependencies
    if dependencies:
        process_script_dependencies(script_path, dependencies)

    # Modify shebang
    modify_shebang(script_path, use_exact=config.use_exact)

    # Make executable
    if config.auto_chmod:
        make_executable(script_path)

    # Create symlink
    symlink_path = None
    shadow_warning = None
    if config.auto_symlink:
        symlink_path, shadow_warning = create_symlink(script_path, config.install_dir, config.script_alias)

    # Verify
    if config.verify_after_install:
        if not verify_script(script_path):
            # Don't fail, just warn (script might not support --help)
            pass

    return symlink_path, shadow_warning
