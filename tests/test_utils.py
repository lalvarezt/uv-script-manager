"""Tests for utils module."""

from pathlib import Path

import pytest
from rich.console import Console

from uv_helper.git_manager import GitError
from uv_helper.utils import (
    ensure_dir,
    expand_path,
    get_repo_name_from_url,
    handle_git_error,
    is_git_url,
    is_local_directory,
    safe_rmtree,
    validate_python_script,
)


class TestEnsureDir:
    """Tests for ensure_dir function."""

    def test_creates_directory(self, tmp_path: Path) -> None:
        """Test that directory is created."""
        test_dir = tmp_path / "test_dir"
        result = ensure_dir(test_dir)

        assert test_dir.exists()
        assert test_dir.is_dir()
        assert result == test_dir

    def test_handles_existing_directory(self, tmp_path: Path) -> None:
        """Test that existing directory is handled correctly."""
        test_dir = tmp_path / "existing"
        test_dir.mkdir()

        result = ensure_dir(test_dir)

        assert test_dir.exists()
        assert result == test_dir

    def test_creates_nested_directories(self, tmp_path: Path) -> None:
        """Test that nested directories are created."""
        test_dir = tmp_path / "a" / "b" / "c"
        result = ensure_dir(test_dir)

        assert test_dir.exists()
        assert result == test_dir


class TestIsGitUrl:
    """Tests for is_git_url function."""

    def test_github_https_url(self) -> None:
        """Test GitHub HTTPS URL."""
        assert is_git_url("https://github.com/user/repo")

    def test_github_ssh_url(self) -> None:
        """Test GitHub SSH URL."""
        assert is_git_url("git@github.com:user/repo.git")

    def test_gitlab_url(self) -> None:
        """Test GitLab URL."""
        assert is_git_url("https://gitlab.com/user/repo")

    def test_ssh_scheme_url(self) -> None:
        """Test ssh:// URL."""
        assert is_git_url("ssh://git@github.com/user/repo.git")

    def test_ssh_scheme_url_with_ref_suffixes(self) -> None:
        """Test ssh:// URL with @tag and #branch suffixes."""
        assert is_git_url("ssh://git@github.com/user/repo.git@v1.0.0")
        assert is_git_url("ssh://git@github.com/user/repo.git#develop")

    def test_url_with_git_extension(self) -> None:
        """Test URL with .git extension."""
        assert is_git_url("https://example.com/repo.git")

    def test_invalid_url(self) -> None:
        """Test invalid URL."""
        assert not is_git_url("https://example.com")
        assert not is_git_url("not a url")


class TestExpandPath:
    """Tests for expand_path function."""

    def test_expands_home_directory(self) -> None:
        """Test that ~ is expanded."""
        result = expand_path("~/test")
        assert "~" not in str(result)
        assert result.is_absolute()

    def test_returns_path_object(self) -> None:
        """Test that Path object is returned."""
        result = expand_path("/tmp/test")
        assert isinstance(result, Path)


class TestCommandAndPathChecks:
    """Tests for command/path helper functions."""

    def test_is_local_directory_handles_expand_errors(self, monkeypatch) -> None:
        """is_local_directory should return False when path expansion fails."""

        def raise_oserror(_path: str) -> Path:
            raise OSError("boom")

        monkeypatch.setattr("uv_helper.utils.expand_path", raise_oserror)

        assert is_local_directory("~/broken") is False


class TestGetRepoNameFromUrl:
    """Tests for get_repo_name_from_url function."""

    def test_github_https_url(self) -> None:
        """Test GitHub HTTPS URL."""
        assert get_repo_name_from_url("https://github.com/user/repo") == "user-repo"

    def test_github_ssh_url(self) -> None:
        """Test GitHub SSH URL."""
        assert get_repo_name_from_url("git@github.com:user/repo.git") == "user-repo"

    def test_url_with_ref(self) -> None:
        """Test URL with ref."""
        assert get_repo_name_from_url("https://github.com/user/repo@v1.0.0") == "user-repo"
        assert get_repo_name_from_url("https://github.com/user/repo#branch") == "user-repo"

    def test_url_with_trailing_slash(self) -> None:
        """Test URL with trailing slash."""
        assert get_repo_name_from_url("https://github.com/user/repo/") == "user-repo"


class TestValidatePythonScript:
    """Tests for validate_python_script function."""

    def test_valid_script_with_shebang(self, tmp_path: Path) -> None:
        """Test valid script with shebang."""
        script = tmp_path / "test.py"
        script.write_text("#!/usr/bin/env python3\nprint('hello')")

        assert validate_python_script(script)

    def test_valid_script_without_shebang(self, tmp_path: Path) -> None:
        """Test valid script without shebang."""
        script = tmp_path / "test.py"
        script.write_text("import sys\nprint('hello')")

        assert validate_python_script(script)

    def test_nonexistent_file(self, tmp_path: Path) -> None:
        """Test nonexistent file."""
        script = tmp_path / "nonexistent.py"
        assert not validate_python_script(script)

    def test_non_python_file(self, tmp_path: Path) -> None:
        """Test non-Python file."""
        script = tmp_path / "test.txt"
        script.write_text("not python")

        assert not validate_python_script(script)

    def test_empty_file(self, tmp_path: Path) -> None:
        """Test empty file."""
        script = tmp_path / "empty.py"
        script.write_text("")

        assert not validate_python_script(script)


class TestErrorHandling:
    """Tests for generic error handlers."""

    def test_handle_git_error_re_raises_giterror_with_guidance(self) -> None:
        """handle_git_error should preserve GitError and print default guidance."""
        console = Console(record=True)

        with pytest.raises(GitError, match="clone failed"):
            handle_git_error(
                console,
                lambda: (_ for _ in ()).throw(GitError("clone failed")),
            )

        output = console.export_text()
        assert "Error:" in output
        assert "Suggestion:" in output


class TestSafeRmtreeAdditionalCases:
    """Additional safe_rmtree checks not covered by security tests."""

    def test_safe_rmtree_rejects_unresolvable_path(self, tmp_path: Path) -> None:
        """safe_rmtree should reject missing paths during strict resolve."""
        missing = tmp_path / "does-not-exist"

        with pytest.raises(ValueError, match="Cannot safely resolve path"):
            safe_rmtree(missing)
