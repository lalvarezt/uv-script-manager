"""Tests for local change classification helpers."""

import shutil
import subprocess
from pathlib import Path

import pytest

from uv_helper.local_changes import (
    _is_uv_managed_script_change,
    _strip_initial_shebang,
    _strip_uv_managed_header,
    clear_managed_script_changes,
    get_local_change_state,
)


def _run_git(repo_path: Path, *args: str) -> str:
    """Run git command and return stripped stdout."""
    result = subprocess.run(
        ["git", *args],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


@pytest.mark.skipif(shutil.which("git") is None, reason="git command required")
class TestLocalChangeClassification:
    """Integration tests for Git-backed local change states."""

    def _init_repo(self, tmp_path: Path) -> Path:
        repo = tmp_path / "repo"
        repo.mkdir()
        _run_git(repo, "init", "-b", "main")
        (repo / "tool.py").write_text("#!/usr/bin/env python3\nprint('hello')\n", encoding="utf-8")
        _run_git(repo, "add", "tool.py")
        _run_git(
            repo,
            "-c",
            "user.name=Test User",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            "initial",
        )
        return repo

    def test_get_local_change_state_clean(self, tmp_path: Path) -> None:
        """Repository with no changes should be classified as clean."""
        repo = self._init_repo(tmp_path)

        assert get_local_change_state(repo, "tool.py") == "clean"

    def test_get_local_change_state_blocking_for_untracked_files(self, tmp_path: Path) -> None:
        """Untracked files should mark local changes as blocking."""
        repo = self._init_repo(tmp_path)
        (repo / "extra.py").write_text("print('extra')\n", encoding="utf-8")

        assert get_local_change_state(repo, "tool.py") == "blocking"

    def test_get_local_change_state_managed_for_uv_header_only_changes(self, tmp_path: Path) -> None:
        """Only uv-managed header edits should be classified as managed."""
        repo = self._init_repo(tmp_path)
        (repo / "tool.py").write_text(
            "#!/usr/bin/env -S uv run --exact --script\n"
            "# /// script\n"
            '# requires-python = ">=3.11"\n'
            "# ///\n"
            "print('hello')\n",
            encoding="utf-8",
        )

        assert get_local_change_state(repo, "tool.py") == "managed"

    def test_clear_managed_script_changes_reverts_script(self, tmp_path: Path) -> None:
        """clear_managed_script_changes should checkout the script and restore clean state."""
        repo = self._init_repo(tmp_path)
        (repo / "tool.py").write_text("#!/usr/bin/env python3\nprint('changed')\n", encoding="utf-8")

        assert clear_managed_script_changes(repo, "tool.py") is True
        assert get_local_change_state(repo, "tool.py") == "clean"


def test_get_local_change_state_returns_unknown_for_non_git_directory(tmp_path: Path) -> None:
    """Non-git directories should return unknown state."""
    repo = tmp_path / "not-a-repo"
    repo.mkdir()
    (repo / "tool.py").write_text("print('x')\n", encoding="utf-8")

    assert get_local_change_state(repo, "tool.py") == "unknown"


def test_clear_managed_script_changes_returns_false_on_checkout_failure(monkeypatch, tmp_path: Path) -> None:
    """clear_managed_script_changes should return False when checkout fails."""

    def raise_checkout(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0], stderr="checkout failed")

    monkeypatch.setattr("uv_helper.local_changes.run_command", raise_checkout)

    assert clear_managed_script_changes(tmp_path, "tool.py") is False


def test_strip_helpers_normalize_uv_managed_and_original_content() -> None:
    """Header stripping helpers should normalize managed and original script content."""
    managed = (
        "#!/usr/bin/env -S uv run --script\n"
        "# /// script\n"
        '# requires-python = ">=3.11"\n'
        "# ///\n"
        "print('hello')\n"
    )
    original = "#!/usr/bin/env python3\nprint('hello')\n"

    assert _strip_uv_managed_header(managed) == "print('hello')\n"
    assert _strip_initial_shebang(original) == "print('hello')\n"


def test_is_uv_managed_script_change_false_when_script_missing(tmp_path: Path) -> None:
    """Managed-change detection should return False for missing script files."""
    assert _is_uv_managed_script_change(tmp_path, "missing.py") is False
