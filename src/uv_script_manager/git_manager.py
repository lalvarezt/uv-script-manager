"""Git operations."""

import subprocess
from pathlib import Path
from typing import Literal

from giturlparse import parse as parse_git_url_base
from pydantic import BaseModel

from .constants import GIT_SHORT_HASH_LENGTH
from .refs import split_source_ref
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
    # Extract ref markers before parsing.
    base_url, ref_type, ref_value = split_source_ref(url)

    parsed = parse_git_url_base(base_url)
    # Convert to HTTPS format and remove .git suffix for consistency
    normalized_url = parsed.url2https.removesuffix(".git")
    return GitRef(base_url=normalized_url, ref_type=ref_type, ref_value=ref_value)


def clone_repository(
    url: str,
    target_dir: Path,
    depth: int = 1,
    ref: str | None = None,
    ref_type: str | None = None,
) -> None:
    """
    Clone a Git repository.

    Args:
        url: Repository URL
        target_dir: Directory to clone into
        depth: Clone depth (1 for shallow clone)
        ref: Specific branch/tag to clone
        ref_type: Type of ref ("branch", "tag", "commit", or "default").
            When "commit", clones without --branch and checks out after.

    Raises:
        GitError: If clone fails
    """
    is_commit = ref_type == "commit"

    cmd = ["git", "clone", "--depth", str(depth)]

    if ref and not is_commit:
        cmd.extend(["--branch", ref])

    cmd.extend([url, str(target_dir)])

    try:
        run_command(cmd, capture_output=True, check=True)
        # For commit refs, fetch the specific commit and checkout after clone
        if ref and is_commit:
            run_command(["git", "fetch", "origin", ref], cwd=target_dir, check=True)
            checkout_ref(target_dir, ref)
    except subprocess.CalledProcessError as e:
        raise GitError(f"Failed to clone repository: {e.stderr}") from e


def fetch_repository(repo_path: Path, fetch_tags: bool = False) -> None:
    """
    Fetch updates from remote repository.

    Args:
        repo_path: Path to repository
        fetch_tags: Whether to fetch tags

    Raises:
        GitError: If fetch fails
    """
    try:
        cmd = ["git", "fetch"]
        if fetch_tags:
            cmd.append("--tags")
        run_command(cmd, cwd=repo_path, check=True)
    except subprocess.CalledProcessError as e:
        raise GitError(f"Failed to fetch repository: {e.stderr}") from e


def is_detached_head(repo_path: Path) -> bool:
    """
    Check if repository is in detached HEAD state.

    Args:
        repo_path: Path to repository

    Returns:
        True if in detached HEAD state
    """
    try:
        result = run_command(
            ["git", "symbolic-ref", "-q", "HEAD"],
            cwd=repo_path,
            check=False,
        )
        # Non-zero exit code means detached HEAD
        return result.returncode != 0
    except subprocess.CalledProcessError:
        return True


def update_repository(repo_path: Path, ref: str | None = None) -> None:
    """
    Update an existing repository.

    For branches: fetches and pulls changes.
    For tags/commits: fetches and checks out the ref.

    Args:
        repo_path: Path to repository
        ref: Optional specific ref (branch, tag, or commit)

    Raises:
        GitError: If update fails
    """
    try:
        # Always fetch with tags to ensure tag refs are available
        fetch_repository(repo_path, fetch_tags=True)

        if ref:
            checkout_ref(repo_path, ref)
        elif is_detached_head(repo_path):
            # Repository may have been previously checked out to tag/commit.
            # For default updates, switch back to the remote default branch.
            default_branch = get_default_branch(repo_path)
            run_command(
                [
                    "git",
                    "fetch",
                    "origin",
                    f"{default_branch}:refs/remotes/origin/{default_branch}",
                ],
                cwd=repo_path,
                check=True,
            )
            run_command(
                ["git", "checkout", "-B", default_branch, f"origin/{default_branch}"],
                cwd=repo_path,
                check=True,
            )

        if is_detached_head(repo_path):
            # Tag or commit - don't pull
            return

        # Branch - pull to get latest
        run_command(["git", "pull"], cwd=repo_path, check=True)
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
        # Fallback: ask remote what HEAD points to.
        # Works even when local clone has detached HEAD from tag/commit checkout.
        try:
            result = run_command(
                ["git", "ls-remote", "--symref", "origin", "HEAD"],
                cwd=repo_path,
                check=True,
            )
            for line in result.stdout.splitlines():
                if line.startswith("ref: ") and line.endswith("\tHEAD"):
                    # Format: ref: refs/heads/main	HEAD
                    return line.split()[1].split("/")[-1]
        except subprocess.CalledProcessError:
            pass

        # Last fallback: current branch (if not detached)
        try:
            result = run_command(
                ["git", "branch", "--show-current"],
                cwd=repo_path,
                check=True,
            )
            branch = result.stdout.strip()
            if branch:
                return branch
            raise GitError("Failed to determine default branch: repository is in detached HEAD state")
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
            ["git", "rev-parse", f"--short={GIT_SHORT_HASH_LENGTH}", "HEAD"],
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
    ref_type: str | None = None,
) -> None:
    """
    Clone repository if not exists, otherwise update it.

    Args:
        url: Repository URL
        ref: Specific branch/tag/commit
        target_dir: Directory to clone into
        depth: Clone depth
        ref_type: Type of ref ("branch", "tag", "commit", or "default")

    Raises:
        GitError: If operation fails
    """
    if target_dir.exists():
        # Repository exists, update it with the specific ref
        update_repository(target_dir, ref)
    else:
        # Clone repository
        clone_repository(url, target_dir, depth=depth, ref=ref, ref_type=ref_type)


def verify_git_available() -> None:
    """
    Verify that git command is available.

    Raises:
        GitError: If git is not available
    """
    try:
        run_command(["git", "--version"], check=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        raise GitError("Git is not installed or not in PATH") from e
