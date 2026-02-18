"""Utility functions."""

import logging
import os
import shutil
import subprocess
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, TypeVar

from giturlparse import parse as parse_git_url_base
from giturlparse import validate as validate_git_url
from pathvalidate import sanitize_filename
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import Confirm

from .refs import split_source_ref

logger = logging.getLogger(__name__)

T = TypeVar("T")


def ensure_dir(path: Path) -> Path:
    """
    Create directory if it doesn't exist.

    Args:
        path: Directory path to create

    Returns:
        The created/existing directory path
    """
    path.mkdir(parents=True, exist_ok=True)
    return path


def is_git_url(url: str) -> bool:
    """
    Validate if string is a Git URL.

    Validates URL format and checks if it can be parsed as a Git URL.
    Handles HTTPS, SSH, and git:// protocols.

    Args:
        url: URL string to validate

    Returns:
        True if valid Git URL, False otherwise
    """
    # Remove optional ref suffixes before validation.
    base_url, _, _ = split_source_ref(url)
    return validate_git_url(base_url)


def is_local_directory(path: str) -> bool:
    """
    Check if path is a local directory.

    Args:
        path: Path string to check

    Returns:
        True if path exists and is a directory, False otherwise
    """
    try:
        expanded = expand_path(path)
        return expanded.is_dir()
    except (OSError, ValueError, RuntimeError):
        # Path resolution or access errors
        return False


def sanitize_directory_name(name: str) -> str:
    """
    Sanitize a directory name to remove invalid characters.

    Uses pathvalidate to ensure the name is valid for filesystem use.
    Replaces invalid characters with hyphens.

    Args:
        name: Directory name to sanitize

    Returns:
        Sanitized directory name
    """
    return sanitize_filename(name, replacement_text="-")


def expand_path(path: str) -> Path:
    """
    Expand ~ and environment variables in path.

    Args:
        path: Path string to expand

    Returns:
        Expanded Path object
    """
    return Path(os.path.expanduser(os.path.expandvars(path))).resolve()


def prompt_confirm(message: str, default: bool = False) -> bool:
    """
    Prompt user for confirmation.

    Args:
        message: Confirmation message
        default: Default value if user just presses Enter

    Returns:
        True if confirmed, False otherwise
    """
    return Confirm.ask(message, default=default)


def run_command(
    cmd: list[str],
    cwd: Path | None = None,
    capture_output: bool = True,
    check: bool = True,
    timeout: float | None = None,
) -> subprocess.CompletedProcess:
    """
    Run a shell command.

    Args:
        cmd: Command and arguments as list
        cwd: Working directory for command
        capture_output: Whether to capture stdout/stderr
        check: Whether to raise exception on non-zero exit
        timeout: Timeout in seconds (None for no timeout)

    Returns:
        CompletedProcess instance

    Raises:
        subprocess.CalledProcessError: If command fails and check=True
        subprocess.TimeoutExpired: If command times out
    """
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=capture_output,
        text=True,
        check=check,
        timeout=timeout,
    )


def get_repo_name_from_url(url: str) -> str:
    """
    Generate a repository name from URL.

    Extracts owner and repository name from any valid Git URL format (HTTPS, SSH, git://, etc.).

    Examples:
        https://github.com/user/repo -> user-repo
        git@github.com:user/repo.git -> user-repo
        https://github.com/user/repo@v1.0.0 -> user-repo

    Args:
        url: Git repository URL

    Returns:
        Repository name (format: owner-repo)
    """
    base_url, _, _ = split_source_ref(url)
    parsed = parse_git_url_base(base_url)
    return f"{parsed.owner}-{parsed.name}"


def validate_python_script(script_path: Path) -> bool:
    """
    Validate that a file is a Python script.

    Args:
        script_path: Path to script file

    Returns:
        True if valid Python script, False otherwise
    """
    if not script_path.exists():
        return False

    if not script_path.suffix == ".py":
        return False

    try:
        # Try to parse the file as Python code to validate syntax
        import ast

        with open(script_path, "r", encoding="utf-8") as f:
            content = f.read()
            # Reject empty or whitespace-only files
            if not content.strip():
                return False
            # Parse to check for valid Python syntax
            ast.parse(content)
        return True
    except (SyntaxError, ValueError):
        # Invalid Python syntax
        return False
    except (OSError, UnicodeDecodeError):
        # File access or encoding errors
        return False


@contextmanager
def progress_spinner(description: str, console: Console) -> Iterator[tuple[Progress, int]]:
    """
    Create a progress spinner context manager.

    Args:
        description: Task description to display
        console: Rich console for output

    Yields:
        Tuple of (progress, task_id)
    """
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task(description, total=None)
        yield progress, task


def safe_rmtree(path: Path) -> None:
    """
    Safely remove a directory tree, preventing symlink attacks.

    Validates that the path is not a symlink before removal to prevent
    following malicious symlinks to sensitive system directories.

    Args:
        path: Directory path to remove

    Raises:
        ValueError: If path is a symlink (security protection)
        OSError: If removal fails
    """
    # Security check: refuse to remove if path is a symlink
    # This prevents attacks where a symlink points to /etc or other sensitive dirs
    if path.is_symlink():
        raise ValueError(f"Refusing to remove symlinked directory: {path}")

    # Additional check: resolve path and ensure it's what we expect
    try:
        resolved = path.resolve(strict=True)
        # Only proceed if path exists and is a directory
        if not resolved.is_dir():
            raise ValueError(f"Path is not a directory: {path}")
    except (OSError, RuntimeError) as e:
        raise ValueError(f"Cannot safely resolve path {path}: {e}") from e

    # Safe to remove - it's a real directory, not a symlink
    shutil.rmtree(path)


def copy_directory_contents(source: Path, dest: Path) -> None:
    """
    Copy all contents from source directory to destination directory.

    Overwrites existing files and directories in destination.

    Args:
        source: Source directory path
        dest: Destination directory path

    Raises:
        OSError: If copy operation fails
    """
    for item in source.iterdir():
        dest_item = dest / item.name
        if item.is_dir():
            if dest_item.exists():
                safe_rmtree(dest_item)
            shutil.copytree(item, dest_item)
        else:
            shutil.copy2(item, dest_item)


def copy_script_file(source_root: Path, script_rel_path: str, dest_root: Path) -> Path:
    """
    Copy one script file from source tree to destination tree.

    Args:
        source_root: Root source directory
        script_rel_path: Relative script path inside source_root
        dest_root: Root destination directory

    Returns:
        Path to the copied script under dest_root

    Raises:
        FileNotFoundError: If source script does not exist
        IsADirectoryError: If source path is not a file
        OSError: If copy operation fails
    """
    source_script = source_root / script_rel_path
    if not source_script.exists():
        raise FileNotFoundError(f"Script not found: {source_script}")
    if not source_script.is_file():
        raise IsADirectoryError(f"Script path is not a file: {source_script}")

    dest_script = dest_root / script_rel_path
    ensure_dir(dest_script.parent)
    shutil.copy2(source_script, dest_script)
    return dest_script


def handle_git_error(console: Console, operation: Callable[[], T], error_prefix: str = "Git") -> T:
    """
    Execute a git operation with consistent error handling.

    Args:
        console: Rich console for error output
        operation: Callable that performs the git operation
        error_prefix: Prefix for error messages (default: "Git")

    Returns:
        Result from the operation callable

    Raises:
        GitError: Re-raised from operation failures
    """
    from .git_manager import GitError

    try:
        return operation()
    except GitError as e:
        console.print(f"[red]Error:[/red] {error_prefix}: {e}")
        console.print("[cyan]Suggestion:[/cyan] Verify git is installed and repository URL is correct")
        raise
