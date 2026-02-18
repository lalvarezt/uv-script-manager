"""Tests for git_manager module."""

import shutil
import subprocess
from pathlib import Path

import pytest

from uv_script_manager.constants import GIT_SHORT_HASH_LENGTH
from uv_script_manager.git_manager import (
    GitError,
    GitRef,
    checkout_ref,
    clone_or_update,
    get_current_commit_hash,
    get_default_branch,
    get_remote_commit_hash,
    is_detached_head,
    parse_git_url,
    verify_git_available,
)


def _run_git(repo_path: Path, *args: str) -> str:
    """Run a git command and return stripped stdout."""
    result = subprocess.run(
        ["git", *args],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _create_origin_repo_with_tag(tmp_path: Path) -> tuple[Path, str, str]:
    """Create an origin repository with a tag on commit 1 and commit 2 on main."""
    origin = tmp_path / "origin"
    origin.mkdir()

    _run_git(origin, "init", "-b", "main")
    (origin / "tool.py").write_text("print('v1')\n", encoding="utf-8")
    _run_git(origin, "add", "tool.py")
    _run_git(
        origin,
        "-c",
        "user.name=Test User",
        "-c",
        "user.email=test@example.com",
        "commit",
        "-m",
        "c1",
    )
    _run_git(origin, "tag", "v1.0.0")

    (origin / "tool.py").write_text("print('v2')\n", encoding="utf-8")
    _run_git(origin, "add", "tool.py")
    _run_git(
        origin,
        "-c",
        "user.name=Test User",
        "-c",
        "user.email=test@example.com",
        "commit",
        "-m",
        "c2",
    )

    tag_commit = _run_git(origin, "rev-parse", f"--short={GIT_SHORT_HASH_LENGTH}", "v1.0.0")
    head_commit = _run_git(origin, "rev-parse", f"--short={GIT_SHORT_HASH_LENGTH}", "HEAD")
    return origin, tag_commit, head_commit


class TestParseGitUrl:
    """Tests for parse_git_url function."""

    def test_url_without_ref(self) -> None:
        """Test URL without ref."""
        result = parse_git_url("https://github.com/user/repo")

        assert result.base_url == "https://github.com/user/repo"
        assert result.ref_type == "default"
        assert result.ref_value is None

    def test_url_with_tag(self) -> None:
        """Test URL with tag."""
        result = parse_git_url("https://github.com/user/repo@v1.0.0")

        assert result.base_url == "https://github.com/user/repo"
        assert result.ref_type == "tag"
        assert result.ref_value == "v1.0.0"

    def test_url_with_branch(self) -> None:
        """Test URL with branch."""
        result = parse_git_url("https://github.com/user/repo#dev")

        assert result.base_url == "https://github.com/user/repo"
        assert result.ref_type == "branch"
        assert result.ref_value == "dev"

    def test_url_with_git_extension(self) -> None:
        """Test URL with .git extension."""
        result = parse_git_url("https://github.com/user/repo.git")

        assert result.base_url == "https://github.com/user/repo"
        assert result.ref_type == "default"
        assert result.ref_value is None

    def test_url_with_git_extension_and_tag(self) -> None:
        """Test URL with .git extension and tag."""
        result = parse_git_url("https://github.com/user/repo.git@v1.0.0")

        assert result.base_url == "https://github.com/user/repo"
        assert result.ref_type == "tag"
        assert result.ref_value == "v1.0.0"

    def test_ssh_scheme_url_without_ref(self) -> None:
        """Test ssh:// URL without ref suffix."""
        result = parse_git_url("ssh://git@github.com/user/repo.git")

        assert result.base_url == "https://github.com/user/repo"
        assert result.ref_type == "default"
        assert result.ref_value is None

    def test_ssh_scheme_url_with_tag_ref(self) -> None:
        """Test ssh:// URL with @tag suffix."""
        result = parse_git_url("ssh://git@github.com/user/repo.git@v2.0.0")

        assert result.base_url == "https://github.com/user/repo"
        assert result.ref_type == "tag"
        assert result.ref_value == "v2.0.0"

    def test_ssh_scheme_url_with_branch_ref(self) -> None:
        """Test ssh:// URL with #branch suffix."""
        result = parse_git_url("ssh://git@github.com/user/repo.git#develop")

        assert result.base_url == "https://github.com/user/repo"
        assert result.ref_type == "branch"
        assert result.ref_value == "develop"

    def test_scp_style_ssh_url_with_tag_ref(self) -> None:
        """Test git@host:path style URL with @tag suffix."""
        result = parse_git_url("git@github.com:user/repo.git@v3.1.4")

        assert result.base_url == "https://github.com/user/repo"
        assert result.ref_type == "tag"
        assert result.ref_value == "v3.1.4"

    def test_git_protocol_url_with_commit_ref(self) -> None:
        """Test git:// URL with @commit suffix."""
        result = parse_git_url("git://github.com/user/repo.git@deadbeef")

        assert result.base_url == "https://github.com/user/repo"
        assert result.ref_type == "commit"
        assert result.ref_value == "deadbeef"


class TestGitRef:
    """Tests for GitRef dataclass."""

    def test_creates_instance(self) -> None:
        """Test creating GitRef instance."""
        ref = GitRef(
            base_url="https://github.com/user/repo",
            ref_type="tag",
            ref_value="v1.0.0",
        )

        assert ref.base_url == "https://github.com/user/repo"
        assert ref.ref_type == "tag"
        assert ref.ref_value == "v1.0.0"

    def test_with_none_ref_value(self) -> None:
        """Test GitRef with None ref_value."""
        ref = GitRef(
            base_url="https://github.com/user/repo",
            ref_type="default",
            ref_value=None,
        )

        assert ref.ref_value is None


class TestGitManagerFallbacks:
    """Unit tests for fallback/error branches in git_manager helpers."""

    def test_get_default_branch_uses_ls_remote_symref_fallback(self, monkeypatch, tmp_path: Path) -> None:
        """When origin/HEAD lookup fails, get_default_branch should parse ls-remote output."""
        calls = {"count": 0}

        def fake_run_command(cmd, cwd=None, check=True):
            calls["count"] += 1
            if calls["count"] == 1:
                raise subprocess.CalledProcessError(1, cmd, stderr="no symbolic-ref")
            if cmd[:3] == ["git", "ls-remote", "--symref"]:
                return subprocess.CompletedProcess(
                    cmd,
                    0,
                    stdout="ref: refs/heads/main\tHEAD\nabc123\tHEAD\n",
                    stderr="",
                )
            raise AssertionError(f"Unexpected command: {cmd}")

        monkeypatch.setattr("uv_script_manager.git_manager.run_command", fake_run_command)

        assert get_default_branch(tmp_path) == "main"

    def test_get_default_branch_uses_current_branch_last_fallback(self, monkeypatch, tmp_path: Path) -> None:
        """When remote lookups fail, get_default_branch should use local current branch."""
        calls = {"count": 0}

        def fake_run_command(cmd, cwd=None, check=True):
            calls["count"] += 1
            if calls["count"] <= 2:
                raise subprocess.CalledProcessError(1, cmd, stderr="failed")
            return subprocess.CompletedProcess(cmd, 0, stdout="feature-x\n", stderr="")

        monkeypatch.setattr("uv_script_manager.git_manager.run_command", fake_run_command)

        assert get_default_branch(tmp_path) == "feature-x"

    def test_get_default_branch_raises_when_detached_and_no_fallbacks(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        """get_default_branch should raise when no branch can be determined."""
        calls = {"count": 0}

        def fake_run_command(cmd, cwd=None, check=True):
            calls["count"] += 1
            if calls["count"] <= 2:
                raise subprocess.CalledProcessError(1, cmd, stderr="failed")
            return subprocess.CompletedProcess(cmd, 0, stdout="\n", stderr="")

        monkeypatch.setattr("uv_script_manager.git_manager.run_command", fake_run_command)

        with pytest.raises(GitError, match="detached HEAD state"):
            get_default_branch(tmp_path)

    @pytest.mark.skipif(shutil.which("git") is None, reason="git command required")
    def test_checkout_ref_falls_back_to_default_branch(self, tmp_path: Path) -> None:
        """checkout_ref should recover when requested branch is missing but default exists."""
        repo = tmp_path / "repo"
        repo.mkdir()

        _run_git(repo, "init", "-b", "main")
        (repo / "tool.py").write_text("print('hi')\n", encoding="utf-8")
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

        assert checkout_ref(repo, "master") is True
        assert _run_git(repo, "branch", "--show-current") == "main"

    def test_get_remote_commit_hash_raises_when_no_ref_found(self, monkeypatch) -> None:
        """get_remote_commit_hash should raise when ls-remote returns empty output."""

        def fake_run_command(cmd, cwd=None, check=True):
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        monkeypatch.setattr("uv_script_manager.git_manager.run_command", fake_run_command)

        with pytest.raises(GitError, match="No commit found"):
            get_remote_commit_hash("https://github.com/user/repo", "missing-ref")

    def test_verify_git_available_raises_when_git_missing(self, monkeypatch) -> None:
        """verify_git_available should raise GitError when git command is unavailable."""

        def raise_file_not_found(cmd, cwd=None, check=True):
            raise FileNotFoundError("git not found")

        monkeypatch.setattr("uv_script_manager.git_manager.run_command", raise_file_not_found)

        with pytest.raises(GitError, match="Git is not installed"):
            verify_git_available()


@pytest.mark.skipif(shutil.which("git") is None, reason="git command required")
class TestCloneOrUpdateIntegration:
    """Integration tests for clone/update behavior without mocks."""

    def test_clone_or_update_tag_then_default_recovers_detached_head(self, tmp_path: Path) -> None:
        """Default updates should recover from detached HEAD after tag checkout."""
        origin, tag_commit, head_commit = _create_origin_repo_with_tag(tmp_path)
        clone_path = tmp_path / "clone"

        clone_or_update(str(origin), "v1.0.0", clone_path, ref_type="tag")
        assert get_current_commit_hash(clone_path) == tag_commit
        assert is_detached_head(clone_path) is True

        clone_or_update(str(origin), None, clone_path)
        assert get_current_commit_hash(clone_path) == head_commit
        assert is_detached_head(clone_path) is False
        assert _run_git(clone_path, "branch", "--show-current") == "main"

    def test_get_default_branch_from_detached_tag_checkout(self, tmp_path: Path) -> None:
        """Default branch resolution should work from detached tag checkouts."""
        origin, _tag_commit, _head_commit = _create_origin_repo_with_tag(tmp_path)
        clone_path = tmp_path / "clone"

        clone_or_update(str(origin), "v1.0.0", clone_path, ref_type="tag")
        assert is_detached_head(clone_path) is True

        assert get_default_branch(clone_path) == "main"
