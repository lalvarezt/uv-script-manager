"""Security tests for UV-Helper.

Tests for path traversal prevention, TOCTOU race conditions, and other security vulnerabilities.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from tests.cli_helpers import _write_config
from uv_helper.cli import cli
from uv_helper.script_installer import ScriptInstallerError, create_symlink
from uv_helper.state import StateManager
from uv_helper.utils import safe_rmtree


class TestPathTraversalPrevention:
    """Test that path traversal attacks are prevented."""

    def test_create_symlink_rejects_path_traversal_in_name(self, tmp_path: Path) -> None:
        """Test that symlink creation rejects path traversal attempts."""
        script_path = tmp_path / "script.py"
        script_path.write_text("print('test')", encoding="utf-8")
        target_dir = tmp_path / "bin"
        target_dir.mkdir()

        # Attempt path traversal in symlink name
        with pytest.raises(ScriptInstallerError, match="Invalid symlink name"):
            create_symlink(script_path, target_dir, "../../etc/passwd")

    def test_create_symlink_rejects_absolute_paths(self, tmp_path: Path) -> None:
        """Test that symlink creation rejects absolute paths."""
        script_path = tmp_path / "script.py"
        script_path.write_text("print('test')", encoding="utf-8")
        target_dir = tmp_path / "bin"
        target_dir.mkdir()

        # Attempt absolute path in symlink name
        with pytest.raises(ScriptInstallerError, match="Invalid symlink name"):
            create_symlink(script_path, target_dir, "/tmp/evil")

    def test_create_symlink_rejects_null_bytes(self, tmp_path: Path) -> None:
        """Test that symlink creation rejects null bytes."""
        script_path = tmp_path / "script.py"
        script_path.write_text("print('test')", encoding="utf-8")
        target_dir = tmp_path / "bin"
        target_dir.mkdir()

        # Attempt null byte injection
        with pytest.raises(ScriptInstallerError, match="Invalid symlink name"):
            create_symlink(script_path, target_dir, "test\x00evil")


class TestTOCTOUProtection:
    """Test that TOCTOU race conditions are handled."""

    def test_create_symlink_handles_concurrent_creation(self, tmp_path: Path) -> None:
        """Test that symlink creation handles existing files."""
        script_path = tmp_path / "script.py"
        script_path.write_text("print('test')", encoding="utf-8")
        target_dir = tmp_path / "bin"
        target_dir.mkdir()

        # Create a file that already exists
        existing = target_dir / "script.py"
        existing.write_text("existing", encoding="utf-8")

        # Should remove existing and create symlink
        symlink, _warning = create_symlink(script_path, target_dir)
        assert symlink.is_symlink()
        assert symlink.resolve() == script_path

    def test_create_symlink_replaces_existing_symlink(self, tmp_path: Path) -> None:
        """Test that symlink creation replaces existing symlinks."""
        script_path = tmp_path / "script.py"
        script_path.write_text("print('test')", encoding="utf-8")
        old_script = tmp_path / "old.py"
        old_script.write_text("print('old')", encoding="utf-8")
        target_dir = tmp_path / "bin"
        target_dir.mkdir()

        # Create existing symlink to different target
        existing_symlink = target_dir / "script.py"
        existing_symlink.symlink_to(old_script)

        # Should replace with new symlink
        new_symlink, _warning = create_symlink(script_path, target_dir)
        assert new_symlink.is_symlink()
        assert new_symlink.resolve() == script_path
        assert new_symlink.resolve() != old_script


class TestSymlinkAttackPrevention:
    """Test that symlink following attacks are prevented."""

    def test_safe_rmtree_rejects_symlink(self, tmp_path: Path) -> None:
        """Test that safe_rmtree refuses to remove symlinked directories."""
        real_dir = tmp_path / "real"
        real_dir.mkdir()
        (real_dir / "important.txt").write_text("data", encoding="utf-8")

        symlink_dir = tmp_path / "symlink"
        symlink_dir.symlink_to(real_dir)

        # Should refuse to remove symlink
        with pytest.raises(ValueError, match="Refusing to remove symlinked directory"):
            safe_rmtree(symlink_dir)

        # Real directory should still exist
        assert real_dir.exists()
        assert (real_dir / "important.txt").exists()

    def test_safe_rmtree_removes_real_directory(self, tmp_path: Path) -> None:
        """Test that safe_rmtree successfully removes real directories."""
        real_dir = tmp_path / "real"
        real_dir.mkdir()
        (real_dir / "file.txt").write_text("data", encoding="utf-8")
        nested = real_dir / "nested"
        nested.mkdir()
        (nested / "nested_file.txt").write_text("nested", encoding="utf-8")

        # Should successfully remove real directory
        safe_rmtree(real_dir)
        assert not real_dir.exists()

    def test_safe_rmtree_rejects_file(self, tmp_path: Path) -> None:
        """Test that safe_rmtree rejects files (not directories)."""
        file_path = tmp_path / "file.txt"
        file_path.write_text("data", encoding="utf-8")

        # Should refuse to remove file
        with pytest.raises(ValueError, match="Path is not a directory"):
            safe_rmtree(file_path)

        # File should still exist
        assert file_path.exists()


class TestValidationCoverage:
    """Test that all entry points have proper validation."""

    def test_script_name_validation_in_install(self, tmp_path: Path, monkeypatch) -> None:
        """Install command should reject path traversal attempts in --script values."""
        runner = CliRunner()

        repo_dir = tmp_path / "repos"
        install_dir = tmp_path / "bin"
        state_file = tmp_path / "state.json"
        config_path = tmp_path / "config.toml"
        _write_config(config_path, repo_dir, install_dir, state_file)

        source_dir = tmp_path / "source"
        source_dir.mkdir()
        (source_dir / "tool.py").write_text("print('tool')\n", encoding="utf-8")
        (tmp_path / "outside.py").write_text("print('outside')\n", encoding="utf-8")

        monkeypatch.setattr("uv_helper.cli.verify_uv_available", lambda: True)

        result = runner.invoke(
            cli,
            [
                "--config",
                str(config_path),
                "install",
                str(source_dir),
                "--script",
                "../outside.py",
                "--no-deps",
            ],
        )

        assert result.exit_code != 0
        assert "Invalid script name" in result.output
        assert StateManager(state_file).get_script("../outside.py") is None
        assert not (repo_dir / "outside.py").exists()

    def test_alias_validation_in_create_symlink(self, tmp_path: Path) -> None:
        """Test that alias names are validated."""
        script_path = tmp_path / "script.py"
        script_path.write_text("print('test')", encoding="utf-8")
        target_dir = tmp_path / "bin"
        target_dir.mkdir()

        # Test various invalid alias names
        invalid_names = [
            "../../../etc/passwd",  # Path traversal
            "/absolute/path",  # Absolute path
            "name\x00evil",  # Null byte
        ]

        for invalid_name in invalid_names:
            with pytest.raises(ScriptInstallerError, match="Invalid symlink name"):
                create_symlink(script_path, target_dir, invalid_name)
