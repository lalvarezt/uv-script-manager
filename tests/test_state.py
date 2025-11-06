"""Tests for state module."""

from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from uv_helper.constants import SourceType
from uv_helper.state import ScriptInfo, StateManager


class TestScriptInfo:
    """Tests for ScriptInfo Pydantic model."""

    def test_model_dump(self, tmp_path: Path) -> None:
        """Test model_dump serialization."""
        script = ScriptInfo(
            name="test.py",
            source_type=SourceType.GIT,
            source_url="https://github.com/user/repo",
            ref="main",
            installed_at=datetime(2025, 1, 1, 12, 0, 0),
            repo_path=tmp_path / "repo",
            symlink_path=tmp_path / "bin" / "test.py",
            dependencies=["requests", "click"],
            commit_hash="abc123",
        )

        result = script.model_dump(mode="json")

        assert result["name"] == "test.py"
        assert result["source_type"] == "git"
        assert result["source_url"] == "https://github.com/user/repo"
        assert result["ref"] == "main"
        assert result["dependencies"] == ["requests", "click"]
        assert result["commit_hash"] == "abc123"
        assert result["installed_at"] == "2025-01-01T12:00:00"
        assert result["repo_path"] == str(tmp_path / "repo")
        assert result["symlink_path"] == str(tmp_path / "bin" / "test.py")

    def test_model_validate(self, tmp_path: Path) -> None:
        """Test model_validate deserialization."""
        data = {
            "name": "test.py",
            "source_type": "git",
            "source_url": "https://github.com/user/repo",
            "ref": "main",
            "installed_at": "2025-01-01T12:00:00",
            "repo_path": str(tmp_path / "repo"),
            "symlink_path": str(tmp_path / "bin" / "test.py"),
            "dependencies": ["requests"],
            "commit_hash": "abc123",
        }

        script = ScriptInfo.model_validate(data)

        assert script.name == "test.py"
        assert script.source_type == "git"
        assert script.source_url == "https://github.com/user/repo"
        assert script.ref == "main"
        assert isinstance(script.installed_at, datetime)
        assert isinstance(script.repo_path, Path)
        assert isinstance(script.symlink_path, Path)
        assert script.dependencies == ["requests"]
        assert script.commit_hash == "abc123"

    def test_validation_error_missing_field(self) -> None:
        """Test that missing required fields raise ValidationError."""
        data = {
            "name": "test.py",
            "source_url": "https://github.com/user/repo",
            # Missing required fields: installed_at, repo_path
        }

        with pytest.raises(ValidationError) as exc_info:
            ScriptInfo.model_validate(data)

        assert "installed_at" in str(exc_info.value)

    def test_validation_default_values(self) -> None:
        """Test that default values are applied correctly."""
        script = ScriptInfo(
            name="test.py",
            source_type=SourceType.GIT,
            source_url="https://github.com/user/repo",
            ref="main",
            installed_at=datetime.now(),
            repo_path=Path("/tmp/repo"),
            commit_hash="abc123",
        )

        assert script.symlink_path is None
        assert script.dependencies == []


class TestStateManager:
    """Tests for StateManager class with TinyDB."""

    def test_add_and_get_script(self, tmp_path: Path) -> None:
        """Test add_script and get_script methods."""
        state_file = tmp_path / "state.json"
        manager = StateManager(state_file)

        script = ScriptInfo(
            name="test.py",
            source_type=SourceType.GIT,
            source_url="https://github.com/user/repo",
            ref="main",
            installed_at=datetime.now(),
            repo_path=Path("/tmp/repo"),
            symlink_path=Path("/tmp/bin/test.py"),
            dependencies=[],
            commit_hash="abc123",
        )

        manager.add_script(script)
        retrieved = manager.get_script("test.py")

        assert retrieved is not None
        assert retrieved.name == "test.py"
        assert retrieved.source_type == "git"
        assert retrieved.source_url == "https://github.com/user/repo"

    def test_get_script_not_found(self, tmp_path: Path) -> None:
        """Test get_script when script doesn't exist."""
        state_file = tmp_path / "state.json"
        manager = StateManager(state_file)

        result = manager.get_script("nonexistent.py")

        assert result is None

    def test_remove_script(self, tmp_path: Path) -> None:
        """Test remove_script method."""
        state_file = tmp_path / "state.json"
        manager = StateManager(state_file)

        script = ScriptInfo(
            name="test.py",
            source_type=SourceType.GIT,
            source_url="https://github.com/user/repo",
            ref="main",
            installed_at=datetime.now(),
            repo_path=Path("/tmp/repo"),
            symlink_path=Path("/tmp/bin/test.py"),
            dependencies=[],
            commit_hash="abc123",
        )
        manager.add_script(script)

        manager.remove_script("test.py")

        assert manager.get_script("test.py") is None

    def test_has_script(self, tmp_path: Path) -> None:
        """Test has_script method."""
        state_file = tmp_path / "state.json"
        manager = StateManager(state_file)

        script = ScriptInfo(
            name="test.py",
            source_type=SourceType.GIT,
            source_url="https://github.com/user/repo",
            ref="main",
            installed_at=datetime.now(),
            repo_path=Path("/tmp/repo"),
            symlink_path=Path("/tmp/bin/test.py"),
            dependencies=[],
            commit_hash="abc123",
        )
        manager.add_script(script)

        assert manager.has_script("test.py")
        assert not manager.has_script("nonexistent.py")

    def test_list_scripts(self, tmp_path: Path) -> None:
        """Test list_scripts method."""
        state_file = tmp_path / "state.json"
        manager = StateManager(state_file)

        script1 = ScriptInfo(
            name="test1.py",
            source_type=SourceType.GIT,
            source_url="https://github.com/user/repo",
            ref="main",
            installed_at=datetime.now(),
            repo_path=Path("/tmp/repo"),
            symlink_path=Path("/tmp/bin/test1.py"),
            dependencies=[],
            commit_hash="abc123",
        )
        script2 = ScriptInfo(
            name="test2.py",
            source_type=SourceType.GIT,
            source_url="https://github.com/user/repo",
            ref="main",
            installed_at=datetime.now(),
            repo_path=Path("/tmp/repo"),
            symlink_path=Path("/tmp/bin/test2.py"),
            dependencies=[],
            commit_hash="abc123",
        )
        manager.add_script(script1)
        manager.add_script(script2)

        scripts = manager.list_scripts()

        assert len(scripts) == 2
        script_names = {s.name for s in scripts}
        assert "test1.py" in script_names
        assert "test2.py" in script_names

    def test_get_scripts_from_repo(self, tmp_path: Path) -> None:
        """Test get_scripts_from_repo method."""
        state_file = tmp_path / "state.json"
        manager = StateManager(state_file)

        repo1 = Path("/tmp/repo1")
        repo2 = Path("/tmp/repo2")

        script1 = ScriptInfo(
            name="test1.py",
            source_type=SourceType.GIT,
            source_url="https://github.com/user/repo1",
            ref="main",
            installed_at=datetime.now(),
            repo_path=repo1,
            symlink_path=Path("/tmp/bin/test1.py"),
            dependencies=[],
            commit_hash="abc123",
        )
        script2 = ScriptInfo(
            name="test2.py",
            source_type=SourceType.GIT,
            source_url="https://github.com/user/repo1",
            ref="main",
            installed_at=datetime.now(),
            repo_path=repo1,
            symlink_path=Path("/tmp/bin/test2.py"),
            dependencies=[],
            commit_hash="def456",
        )
        script3 = ScriptInfo(
            name="test3.py",
            source_type=SourceType.GIT,
            source_url="https://github.com/user/repo2",
            ref="main",
            installed_at=datetime.now(),
            repo_path=repo2,
            symlink_path=Path("/tmp/bin/test3.py"),
            dependencies=[],
            commit_hash="ghi789",
        )

        manager.add_script(script1)
        manager.add_script(script2)
        manager.add_script(script3)

        scripts_from_repo1 = manager.get_scripts_from_repo(repo1)

        assert len(scripts_from_repo1) == 2
        script_names = {s.name for s in scripts_from_repo1}
        assert "test1.py" in script_names
        assert "test2.py" in script_names
        assert "test3.py" not in script_names

    def test_upsert_script(self, tmp_path: Path) -> None:
        """Test that add_script updates existing scripts."""
        state_file = tmp_path / "state.json"
        manager = StateManager(state_file)

        script = ScriptInfo(
            name="test.py",
            source_type=SourceType.GIT,
            source_url="https://github.com/user/repo",
            ref="main",
            installed_at=datetime(2025, 1, 1),
            repo_path=Path("/tmp/repo"),
            symlink_path=Path("/tmp/bin/test.py"),
            dependencies=[],
            commit_hash="abc123",
        )
        manager.add_script(script)

        # Update with new commit hash
        updated_script = ScriptInfo(
            name="test.py",
            source_type=SourceType.GIT,
            source_url="https://github.com/user/repo",
            ref="main",
            installed_at=datetime(2025, 1, 2),
            repo_path=Path("/tmp/repo"),
            symlink_path=Path("/tmp/bin/test.py"),
            dependencies=["requests"],
            commit_hash="def456",
        )
        manager.add_script(updated_script)

        retrieved = manager.get_script("test.py")
        assert retrieved is not None
        assert retrieved.commit_hash == "def456"
        assert retrieved.dependencies == ["requests"]

        # Verify only one entry exists
        all_scripts = manager.list_scripts()
        assert len(all_scripts) == 1

    def test_empty_state(self, tmp_path: Path) -> None:
        """Test that a new StateManager starts with empty state."""
        state_file = tmp_path / "state.json"
        manager = StateManager(state_file)

        scripts = manager.list_scripts()

        assert len(scripts) == 0

    def test_persistence(self, tmp_path: Path) -> None:
        """Test that state persists across StateManager instances."""
        state_file = tmp_path / "state.json"

        # Create and add script in first instance
        manager1 = StateManager(state_file)
        script = ScriptInfo(
            name="test.py",
            source_type=SourceType.GIT,
            source_url="https://github.com/user/repo",
            ref="main",
            installed_at=datetime(2025, 1, 1, 12, 0, 0),
            repo_path=Path("/tmp/repo"),
            symlink_path=Path("/tmp/bin/test.py"),
            dependencies=["requests"],
            commit_hash="abc123",
        )
        manager1.add_script(script)

        # Create new instance and verify
        manager2 = StateManager(state_file)
        retrieved = manager2.get_script("test.py")

        assert retrieved is not None
        assert retrieved.name == "test.py"
        assert retrieved.source_url == "https://github.com/user/repo"
        assert retrieved.commit_hash == "abc123"
