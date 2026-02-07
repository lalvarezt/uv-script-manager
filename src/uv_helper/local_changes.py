"""Local Git change classification helpers."""

import subprocess
from pathlib import Path
from typing import Literal

from .constants import SCRIPT_METADATA_END, SCRIPT_METADATA_START, SHEBANG_UV_RUN, SHEBANG_UV_RUN_EXACT
from .utils import run_command

LocalChangeState = Literal["clean", "managed", "blocking", "unknown"]


def _collect_git_change_sets(repo_path: Path) -> tuple[set[str], set[str], set[str]] | None:
    """Collect unstaged, staged, and untracked paths for a repository."""
    try:
        unstaged = {
            line.strip()
            for line in run_command(
                ["git", "diff", "--name-only"], cwd=repo_path, check=True
            ).stdout.splitlines()
            if line.strip()
        }
        staged = {
            line.strip()
            for line in run_command(
                ["git", "diff", "--name-only", "--cached"],
                cwd=repo_path,
                check=True,
            ).stdout.splitlines()
            if line.strip()
        }
        untracked = {
            line.strip()
            for line in run_command(
                ["git", "ls-files", "--others", "--exclude-standard"],
                cwd=repo_path,
                check=True,
            ).stdout.splitlines()
            if line.strip()
        }
    except subprocess.CalledProcessError:
        return None

    return unstaged, staged, untracked


def get_local_change_state(repo_path: Path, script_rel_path: str) -> LocalChangeState:
    """Classify local changes for a managed script repository."""
    if not repo_path.exists():
        return "unknown"

    script_rel_path = Path(script_rel_path).as_posix()

    change_sets = _collect_git_change_sets(repo_path)
    if change_sets is None:
        return "unknown"
    unstaged, staged, untracked = change_sets

    if not unstaged and not staged and not untracked:
        return "clean"

    if staged or untracked:
        return "blocking"

    # Unstaged-only changes: allow only uv-managed changes in the target script.
    for changed_path in unstaged:
        if changed_path != script_rel_path:
            return "blocking"
        if not _is_uv_managed_script_change(repo_path, changed_path):
            return "blocking"

    return "managed"


def clear_managed_script_changes(repo_path: Path, script_rel_path: str) -> bool:
    """Discard uv-managed local changes for a script file."""
    script_rel_path = Path(script_rel_path).as_posix()
    try:
        run_command(["git", "checkout", "--", script_rel_path], cwd=repo_path, check=True)
        return True
    except subprocess.CalledProcessError:
        return False


def get_local_change_details(repo_path: Path, script_rel_path: str) -> str | None:
    """Return a concise, actionable detail message for local change state."""
    if not repo_path.exists():
        return "Repository path is missing."

    script_rel_path = Path(script_rel_path).as_posix()

    change_sets = _collect_git_change_sets(repo_path)
    if change_sets is None:
        return "Unable to inspect Git status for this repository."
    unstaged, staged, untracked = change_sets

    if not unstaged and not staged and not untracked:
        return None

    if staged:
        return _format_changed_paths("Staged changes present", sorted(staged))

    if untracked:
        return _format_changed_paths("Untracked files present", sorted(untracked))

    non_script_changes = [path for path in sorted(unstaged) if path != script_rel_path]
    if non_script_changes:
        return _format_changed_paths("Uncommitted changes in other files", non_script_changes)

    if _is_uv_managed_script_change(repo_path, script_rel_path):
        return "Only uv-managed shebang/metadata changes are present."

    return f"Script '{script_rel_path}' has custom uncommitted edits."


def _is_uv_managed_script_change(repo_path: Path, script_rel_path: str) -> bool:
    """Check whether a script change is only uv-managed header metadata."""
    script_path = repo_path / script_rel_path
    if not script_path.exists():
        return False

    try:
        head_content = run_command(
            ["git", "show", f"HEAD:{script_rel_path}"], cwd=repo_path, check=True
        ).stdout
    except subprocess.CalledProcessError:
        return False

    try:
        working_content = script_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False

    working_normalized = _strip_uv_managed_header(working_content)
    head_normalized = _strip_initial_shebang(head_content)
    return working_normalized == head_normalized


def _format_changed_paths(prefix: str, paths: list[str]) -> str:
    """Format a compact path preview for human-readable status details."""
    if not paths:
        return prefix

    preview = ", ".join(paths[:3])
    remainder = len(paths) - 3
    if remainder > 0:
        return f"{prefix}: {preview}, +{remainder} more."
    return f"{prefix}: {preview}."


def _strip_uv_managed_header(content: str) -> str:
    """Strip uv-managed shebang and PEP 723 metadata from file content."""
    lines = content.splitlines(keepends=True)

    if not lines:
        return content

    shebangs = {SHEBANG_UV_RUN_EXACT.strip(), SHEBANG_UV_RUN.strip()}
    if lines and lines[0].strip() in shebangs:
        lines = lines[1:]

    if lines and lines[0].strip() == SCRIPT_METADATA_START:
        for idx, line in enumerate(lines[1:], start=1):
            if line.strip() == SCRIPT_METADATA_END:
                lines = lines[idx + 1 :]
                break

    return "".join(lines)


def _strip_initial_shebang(content: str) -> str:
    """Strip first-line shebang from original script content."""
    lines = content.splitlines(keepends=True)
    if lines and lines[0].startswith("#!"):
        return "".join(lines[1:])
    return content
