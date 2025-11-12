"""Utility functions for UV-Helper."""

import logging
import os
import shutil
import subprocess
import time
from collections.abc import Callable
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from typing import Iterator, ParamSpec, TypeVar, cast

from giturlparse import parse as parse_git_url_base
from giturlparse import validate as validate_git_url
from pathvalidate import sanitize_filename
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import Confirm

logger = logging.getLogger(__name__)

T = TypeVar("T")
P = ParamSpec("P")


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
    # Remove ref markers before validation
    base_url = url
    if "@" in url and not url.startswith("git@"):
        base_url = url.rsplit("@", 1)[0]
    elif "#" in url:
        base_url = url.rsplit("#", 1)[0]

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


def check_command_exists(cmd: str) -> bool:
    """
    Check if a command exists in PATH.

    Args:
        cmd: Command name to check

    Returns:
        True if command exists, False otherwise
    """
    return shutil.which(cmd) is not None


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
    # Remove ref markers before parsing
    base_url = url
    if "@" in url and not url.startswith("git@"):
        base_url = url.rsplit("@", 1)[0]
    elif "#" in url:
        base_url = url.rsplit("#", 1)[0]

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


def exponential_backoff(attempt: int, base: float = 2.0, max_delay: float = 60.0) -> float:
    """
    Calculate exponential backoff delay.

    Args:
        attempt: Retry attempt number (0-indexed)
        base: Base multiplier for exponential growth
        max_delay: Maximum delay in seconds

    Returns:
        Delay in seconds
    """
    delay = base**attempt
    return min(delay, max_delay)


def retry(
    max_attempts: int = 3,
    backoff: Callable[[int], float] = exponential_backoff,
    exceptions: tuple[type[Exception], ...] = (Exception,),
    on_retry: Callable[[Exception, int], None] | None = None,
):
    """
    Decorator to retry a function on failure with exponential backoff.

    Args:
        max_attempts: Maximum number of attempts (default: 3)
        backoff: Function that calculates delay based on attempt number
        exceptions: Tuple of exception types to catch and retry
        on_retry: Callback function called on each retry (exception, attempt_num)

    Examples:
        @retry(max_attempts=4, exceptions=(GitError, ConnectionError))
        def clone_repository(url: str) -> bool:
            # ... git clone logic ...
            pass
    """

    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            last_exception = None

            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e

                    # Don't retry on last attempt
                    if attempt == max_attempts - 1:
                        break

                    # Calculate delay
                    delay = backoff(attempt)

                    # Call retry callback if provided
                    if on_retry:
                        on_retry(e, attempt + 1)

                    # Wait before retry
                    time.sleep(delay)

            # All attempts failed - raise last exception
            if last_exception:
                raise last_exception

            # Should never reach here
            raise RuntimeError("Retry logic error")

        return wrapper

    return decorator


class ErrorContext:
    """Context for error handling with actionable guidance."""

    def __init__(self, error_prefix: str, suggestions: dict[type[Exception], str] | None = None):
        """
        Initialize error context.

        Args:
            error_prefix: Prefix for error messages
            suggestions: Mapping of exception types to actionable suggestions
        """
        self.error_prefix = error_prefix
        self.suggestions = suggestions or {}


def handle_operation(
    console: Console,
    operation: Callable[[], T],
    context: ErrorContext,
    error_types: tuple[type[Exception], ...] | None = None,
    reraise: bool = True,
) -> T | None:
    """
    Execute an operation with comprehensive error handling and actionable guidance.

    This generalizes error handling across all operations (git, file, network, etc.)
    and provides users with helpful suggestions for common failures.

    Args:
        console: Rich console for output
        operation: Callable that performs the operation
        context: Error context with prefix and suggestions
        error_types: Tuple of exception types to catch (None = catch all)
        reraise: Whether to re-raise the exception after logging

    Returns:
        Result from the operation callable, or None if error and not reraising

    Raises:
        Exception: Re-raises caught exceptions if reraise=True

    Examples:
        context = ErrorContext(
            "Git clone",
            suggestions={
                GitError: "Check network connection and repository URL"
            }
        )
        handle_operation(console, lambda: clone_repo(url), context)
    """
    try:
        return operation()
    except Exception as e:
        # Check if we should handle this exception type
        if error_types and not isinstance(e, error_types):
            raise

        # Display error message
        console.print(f"[red]Error:[/red] {context.error_prefix}: {e}")

        # Show actionable suggestion if available
        suggestion = context.suggestions.get(type(e))
        if suggestion:
            console.print(f"[cyan]Suggestion:[/cyan] {suggestion}")

        # Show generic help
        elif isinstance(e, (PermissionError, OSError)):
            console.print("[cyan]Suggestion:[/cyan] Check file permissions and disk space")
        elif isinstance(e, (ConnectionError, TimeoutError)):
            console.print("[cyan]Suggestion:[/cyan] Check your internet connection")

        if reraise:
            raise
        return None


def handle_git_error(console: Console, operation: Callable[[], T], error_prefix: str = "Git") -> T:
    """
    Execute a git operation with consistent error handling.

    This is a backward-compatible wrapper around handle_operation().
    New code should use handle_operation() directly.

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

    context = ErrorContext(
        error_prefix,
        suggestions={
            GitError: "Verify git is installed and repository URL is correct",
            PermissionError: "Check repository directory permissions",
            FileNotFoundError: "Ensure git is in your PATH: which git",
        },
    )

    # handle_operation returns T | None, but with reraise=True (default) it always returns T or raises
    result = handle_operation(console, operation, context, error_types=(GitError,))
    return cast(T, result)
