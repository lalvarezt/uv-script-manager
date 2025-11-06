"""Git operations for UV-Helper."""

import subprocess
from pathlib import Path
from typing import Literal

from giturlparse import parse as parse_git_url_base
from pydantic import BaseModel

from .constants import GIT_SHORT_HASH_LENGTH
from .utils import run_command


class GitError(Exception):
    """
    Raised when a Git operation fails.

    This exception is raised for various Git-related failures including:
    - Clone failures (invalid URL, network issues, authentication problems)
    - Update/pull failures (merge conflicts, detached HEAD state)
    - Checkout failures (invalid branch/tag/commit reference)
    - Git not available in PATH

    The error message typically includes stderr output from the git command.
    """

    pass


class GitRef(BaseModel):
    """Git reference information.

    Pydantic model for validated Git reference parsing with strict ref_type validation.
    """

    base_url: str
    ref_type: Literal["branch", "tag", "commit", "default"]
    ref_value: str | None


def parse_git_url(url: str) -> GitRef:
    """
    Parse Git URL and extract ref information.

    Handles custom ref markers:
    - @ suffix for tags/commits (e.g., repo@v1.0.0)
    - # suffix for branches (e.g., repo#develop)

    Examples:
        https://github.com/user/repo@v1.0.0
        -> GitRef(base_url="https://github.com/user/repo",
                  ref_type="tag", ref_value="v1.0.0")

        https://github.com/user/repo#dev
        -> GitRef(base_url="https://github.com/user/repo",
                  ref_type="branch", ref_value="dev")

    Args:
        url: Git repository URL

    Returns:
        GitRef instance with parsed information
    """
    # Extract ref markers before parsing
    ref_type, ref_value = "default", None
    base_url = url

    # Parse @ suffix for tags/commits, but exclude SSH URLs (git@github.com:...)
    # where @ is part of the host specification, not a ref delimiter
    if "@" in url and not url.startswith("git@"):
        base_url, ref_value = url.rsplit("@", 1)  # rsplit ensures we split on the last @
        ref_type = "tag"
    # Parse # suffix for branch specification
    elif "#" in url:
        base_url, ref_value = url.rsplit("#", 1)
        ref_type = "branch"

    parsed = parse_git_url_base(base_url)
    # Convert to HTTPS format and remove .git suffix for consistency
    normalized_url = parsed.url2https.removesuffix(".git")
    return GitRef(base_url=normalized_url, ref_type=ref_type, ref_value=ref_value)


def clone_repository(
    url: str,
    target_dir: Path,
    depth: int = 1,
    ref: str | None = None,
) -> bool:
    """
    Clone a Git repository.

    Args:
        url: Repository URL
        target_dir: Directory to clone into
        depth: Clone depth (1 for shallow clone)
        ref: Specific branch/tag to clone

    Returns:
        True if successful

    Raises:
        GitError: If clone fails
    """
    cmd = ["git", "clone", "--depth", str(depth)]

    if ref:
        cmd.extend(["--branch", ref])

    cmd.extend([url, str(target_dir)])

    try:
        run_command(cmd, capture_output=True, check=True)
        return True
    except subprocess.CalledProcessError as e:
        raise GitError(f"Failed to clone repository: {e.stderr}") from e


def update_repository(repo_path: Path) -> bool:
    """
    Update an existing repository (git pull).

    Args:
        repo_path: Path to repository

    Returns:
        True if successful

    Raises:
        GitError: If update fails
    """
    try:
        # Fetch latest changes
        run_command(["git", "fetch", "origin"], cwd=repo_path, check=True)

        # Pull changes
        run_command(["git", "pull"], cwd=repo_path, check=True)

        return True
    except subprocess.CalledProcessError as e:
        raise GitError(f"Failed to update repository: {e.stderr}") from e


def get_default_branch(repo_path: Path) -> str:
    """
    Get the default branch of a repository.

    Args:
        repo_path: Path to repository

    Returns:
        Default branch name

    Raises:
        GitError: If unable to determine default branch
    """
    try:
        # Try to get the default branch from origin/HEAD
        result = run_command(
            ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
            cwd=repo_path,
            check=True,
        )
        # Output: refs/remotes/origin/main
        default_branch = result.stdout.strip().split("/")[-1]
        return default_branch
    except subprocess.CalledProcessError:
        # Fall back to checking what branch we're on
        try:
            result = run_command(
                ["git", "branch", "--show-current"],
                cwd=repo_path,
                check=True,
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            raise GitError(f"Failed to determine default branch: {e.stderr}") from e


def checkout_ref(repo_path: Path, ref: str) -> bool:
    """
    Checkout a specific ref (branch, tag, or commit).

    Args:
        repo_path: Path to repository
        ref: Reference to checkout

    Returns:
        True if successful

    Raises:
        GitError: If checkout fails
    """
    try:
        run_command(["git", "checkout", ref], cwd=repo_path, check=True)
        return True
    except subprocess.CalledProcessError as e:
        # Fallback mechanism: If the requested ref doesn't exist (e.g., user specified
        # 'main' but repo uses 'master'), attempt to checkout the repository's actual
        # default branch. This provides better UX when users make common assumptions.
        try:
            default_branch = get_default_branch(repo_path)
            if default_branch != ref:
                # Only attempt fallback if the default is actually different
                run_command(["git", "checkout", default_branch], cwd=repo_path, check=True)
                return True
        except (GitError, subprocess.CalledProcessError):
            # Fallback also failed - original error is more informative
            pass
        raise GitError(f"Failed to checkout ref '{ref}': {e.stderr}") from e


def get_current_commit_hash(repo_path: Path) -> str:
    """
    Get current commit hash.

    Args:
        repo_path: Path to repository

    Returns:
        Commit hash (short form)

    Raises:
        GitError: If getting commit hash fails
    """
    try:
        result = run_command(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_path,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        raise GitError(f"Failed to get commit hash: {e.stderr}") from e


def get_remote_commit_hash(url: str, ref: str = "HEAD") -> str:
    """
    Get remote commit hash without cloning.

    Args:
        url: Repository URL
        ref: Reference (branch, tag, or HEAD)

    Returns:
        Commit hash (short form)

    Raises:
        GitError: If getting remote commit hash fails
    """
    try:
        result = run_command(
            ["git", "ls-remote", url, ref],
            check=True,
        )
        # Output format: "<hash>\t<ref>"
        output = result.stdout.strip()
        if output:
            commit_hash = output.split()[0]
            return commit_hash[:GIT_SHORT_HASH_LENGTH]  # Short hash
        raise GitError(f"No commit found for ref '{ref}'")
    except subprocess.CalledProcessError as e:
        raise GitError(f"Failed to get remote commit hash: {e.stderr}") from e


def clone_or_update(
    url: str,
    ref: str | None,
    target_dir: Path,
    depth: int = 1,
) -> bool:
    """
    Clone repository if not exists, otherwise update it.

    Args:
        url: Repository URL
        ref: Specific branch/tag/commit
        target_dir: Directory to clone into
        depth: Clone depth

    Returns:
        True if successful

    Raises:
        GitError: If operation fails
    """
    if target_dir.exists():
        # Repository exists, update it
        update_repository(target_dir)
        if ref:
            checkout_ref(target_dir, ref)
    else:
        # Clone repository
        clone_repository(url, target_dir, depth=depth, ref=ref)

    return True


def verify_git_available() -> bool:
    """
    Verify that git command is available.

    Returns:
        True if git is available

    Raises:
        GitError: If git is not available
    """
    try:
        run_command(["git", "--version"], check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        raise GitError("Git is not installed or not in PATH") from e
