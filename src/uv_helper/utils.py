"""Utility functions for UV-Helper."""

import os
import shutil
import subprocess
from pathlib import Path

from giturlparse import parse as parse_git_url_base
from giturlparse import validate as validate_git_url
from pathvalidate import sanitize_filename
from rich.prompt import Confirm


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
    except Exception:
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
) -> subprocess.CompletedProcess:
    """
    Run a shell command.

    Args:
        cmd: Command and arguments as list
        cwd: Working directory for command
        capture_output: Whether to capture stdout/stderr
        check: Whether to raise exception on non-zero exit

    Returns:
        CompletedProcess instance

    Raises:
        subprocess.CalledProcessError: If command fails and check=True
    """
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=capture_output,
        text=True,
        check=check,
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
    except Exception:
        # Other errors (encoding, I/O, etc.)
        return False
