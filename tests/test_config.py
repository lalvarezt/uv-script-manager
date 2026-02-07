"""Tests for config module."""

import tomllib
from pathlib import Path

import pytest

import uv_helper.config as config_module
from uv_helper.config import (
    CURRENT_CONFIG_SCHEMA_VERSION,
    DEFAULT_CONFIG_TEMPLATE_PATH,
    Config,
    create_default_config,
    get_config_path,
    load_config,
)


class TestConfig:
    """Tests for Config model."""

    def test_config_creation_with_defaults(self) -> None:
        """Test creating Config with default values."""
        config = Config.model_validate(
            {
                "global": {
                    "paths": {
                        "repo_dir": "/tmp/repos",
                        "install_dir": "/tmp/bin",
                        "state_file": "/tmp/state.json",
                    },
                    "git": {},
                    "install": {},
                },
                "commands": {
                    "list": {},
                },
            }
        )

        assert config.repo_dir == Path("/tmp/repos")
        assert config.install_dir == Path("/tmp/bin")
        assert config.state_file == Path("/tmp/state.json")
        assert config.clone_depth == 1
        assert config.auto_symlink is True
        assert config.verify_after_install is True
        assert config.auto_chmod is True
        assert config.use_exact_flag is True
        assert config.schema_version == CURRENT_CONFIG_SCHEMA_VERSION

    def test_config_path_expansion(self) -> None:
        """Test that ~ is expanded in path fields."""
        config = Config.model_validate(
            {
                "global": {
                    "paths": {
                        "repo_dir": "~/repos",
                        "install_dir": "~/bin",
                        "state_file": "~/state.json",
                    },
                    "git": {},
                    "install": {},
                },
                "commands": {
                    "list": {},
                },
            }
        )

        assert "~" not in str(config.repo_dir)
        assert "~" not in str(config.install_dir)
        assert "~" not in str(config.state_file)
        assert config.repo_dir.is_absolute()
        assert config.install_dir.is_absolute()
        assert config.state_file.is_absolute()

    def test_config_validation_clone_depth_minimum(self) -> None:
        """Test that clone_depth must be >= 1."""
        with pytest.raises(ValueError):
            Config.model_validate(
                {
                    "global": {
                        "paths": {
                            "repo_dir": "/tmp/repos",
                            "install_dir": "/tmp/bin",
                            "state_file": "/tmp/state.json",
                        },
                        "git": {"clone_depth": 0},
                        "install": {},
                    },
                    "commands": {
                        "list": {},
                    },
                }
            )

    def test_config_load_roundtrip(self, tmp_path: Path) -> None:
        """Test that custom config values are loaded correctly."""
        config_file = tmp_path / "config.toml"
        config_file.write_text(
            f"""
[global.paths]
repo_dir = "{tmp_path / "repos"}"
install_dir = "{tmp_path / "bin"}"
state_file = "{tmp_path / "state.json"}"

[global.git]
clone_depth = 5

[global.install]
auto_symlink = false
verify_after_install = false
auto_chmod = false
use_exact_flag = false
""",
            encoding="utf-8",
        )

        loaded_config = load_config(config_file)
        assert loaded_config.repo_dir == tmp_path / "repos"
        assert loaded_config.install_dir == tmp_path / "bin"
        assert loaded_config.state_file == tmp_path / "state.json"
        assert loaded_config.clone_depth == 5
        assert loaded_config.auto_symlink is False
        assert loaded_config.verify_after_install is False
        assert loaded_config.auto_chmod is False
        assert loaded_config.use_exact_flag is False

    def test_load_config_creates_directories(self, tmp_path: Path) -> None:
        """Test that load_config() creates parent directories when copying defaults."""
        nested_dir = tmp_path / "a" / "b" / "c"
        config_file = nested_dir / "config.toml"

        load_config(config_file)
        assert config_file.exists()
        assert nested_dir.exists()


class TestGetConfigPath:
    """Tests for get_config_path function."""

    def test_get_config_path_default(self, monkeypatch) -> None:
        """Test default config path when no env var is set."""
        monkeypatch.delenv("UV_HELPER_CONFIG", raising=False)

        path = get_config_path()

        assert path.is_absolute()
        assert str(path).endswith(".config/uv-helper/config.toml")
        assert "~" not in str(path)

    def test_get_config_path_from_env(self, monkeypatch, tmp_path: Path) -> None:
        """Test that UV_HELPER_CONFIG env var takes priority."""
        custom_path = tmp_path / "custom-config.toml"
        monkeypatch.setenv("UV_HELPER_CONFIG", str(custom_path))

        path = get_config_path()

        assert path == custom_path

    def test_get_config_path_expands_tilde(self, monkeypatch) -> None:
        """Test that ~ is expanded in UV_HELPER_CONFIG."""
        monkeypatch.setenv("UV_HELPER_CONFIG", "~/my-config.toml")

        path = get_config_path()

        assert "~" not in str(path)
        assert path.is_absolute()


class TestCreateDefaultConfig:
    """Tests for create_default_config function."""

    def test_create_default_config(self) -> None:
        """Test that create_default_config returns expected defaults."""
        config = create_default_config()

        assert isinstance(config, Config)
        assert config.clone_depth == 1
        assert config.auto_symlink is True
        assert config.verify_after_install is True
        assert config.auto_chmod is True
        assert config.use_exact_flag is True
        assert config.schema_version == CURRENT_CONFIG_SCHEMA_VERSION

    def test_default_paths_are_absolute(self) -> None:
        """Test that all default paths are absolute."""
        config = create_default_config()

        assert config.repo_dir.is_absolute()
        assert config.install_dir.is_absolute()
        assert config.state_file.is_absolute()
        assert "~" not in str(config.repo_dir)
        assert "~" not in str(config.install_dir)
        assert "~" not in str(config.state_file)


class TestLoadConfig:
    """Tests for load_config function."""

    def test_load_config_migrates_legacy_layout(self, tmp_path: Path) -> None:
        """Test that legacy config sections are migrated to the current layout."""
        config_file = tmp_path / "legacy.toml"
        config_file.write_text(
            f"""
[paths]
repo_dir = "{tmp_path / "legacy-repos"}"
install_dir = "{tmp_path / "legacy-bin"}"
state_file = "{tmp_path / "legacy-state.json"}"

[git]
clone_depth = 7

[install]
auto_symlink = false
verify_after_install = false
auto_chmod = false
use_exact_flag = false
""",
            encoding="utf-8",
        )

        config = load_config(config_file)

        assert config.repo_dir == tmp_path / "legacy-repos"
        assert config.install_dir == tmp_path / "legacy-bin"
        assert config.state_file == tmp_path / "legacy-state.json"
        assert config.clone_depth == 7
        assert config.auto_symlink is False
        assert config.verify_after_install is False
        assert config.auto_chmod is False
        assert config.use_exact_flag is False
        assert config.schema_version == CURRENT_CONFIG_SCHEMA_VERSION

        migrated = tomllib.loads(config_file.read_text(encoding="utf-8"))
        assert migrated["meta"]["schema_version"] == CURRENT_CONFIG_SCHEMA_VERSION
        assert "global" in migrated
        assert "paths" not in migrated
        assert "git" not in migrated
        assert "install" not in migrated
        assert "commands" not in migrated or "list" not in migrated["commands"]

    def test_load_config_skips_migration_when_schema_is_current(self, tmp_path: Path, monkeypatch) -> None:
        """Test that migration logic is skipped when schema version is already current."""
        config_file = tmp_path / "current.toml"
        config_file.write_text(
            f"""
[meta]
schema_version = {CURRENT_CONFIG_SCHEMA_VERSION}

[global.paths]
repo_dir = "{tmp_path / "repos"}"
install_dir = "{tmp_path / "bin"}"
state_file = "{tmp_path / "state.json"}"
""",
            encoding="utf-8",
        )
        original_content = config_file.read_text(encoding="utf-8")

        def should_not_run(data):  # pragma: no cover - guard against unexpected call
            raise AssertionError("migration should not run")

        monkeypatch.setitem(config_module.CONFIG_MIGRATIONS, 1, should_not_run)

        config = load_config(config_file)

        assert config.schema_version == CURRENT_CONFIG_SCHEMA_VERSION
        assert config_file.read_text(encoding="utf-8") == original_content

    def test_load_config_prefers_new_layout_when_both_exist(self, tmp_path: Path) -> None:
        """Test that new layout values override legacy values when both are present."""
        config_file = tmp_path / "mixed.toml"
        config_file.write_text(
            f"""
[paths]
repo_dir = "{tmp_path / "legacy-repos"}"

[global.paths]
repo_dir = "{tmp_path / "new-repos"}"
install_dir = "{tmp_path / "new-bin"}"
state_file = "{tmp_path / "new-state.json"}"
""",
            encoding="utf-8",
        )

        config = load_config(config_file)

        assert config.repo_dir == tmp_path / "new-repos"
        assert config.install_dir == tmp_path / "new-bin"
        assert config.state_file == tmp_path / "new-state.json"

    def test_load_config_from_file(self, tmp_path: Path) -> None:
        """Test loading config from existing TOML file."""
        config_file = tmp_path / "config.toml"
        config_file.write_text(
            f"""
[global.paths]
repo_dir = "{tmp_path / "repos"}"
install_dir = "{tmp_path / "bin"}"
state_file = "{tmp_path / "state.json"}"

[global.git]
clone_depth = 3

[global.install]
auto_symlink = false
verify_after_install = false
auto_chmod = false
use_exact_flag = false
""",
            encoding="utf-8",
        )

        config = load_config(config_file)

        assert config.repo_dir == tmp_path / "repos"
        assert config.install_dir == tmp_path / "bin"
        assert config.state_file == tmp_path / "state.json"
        assert config.clone_depth == 3
        assert config.auto_symlink is False
        assert config.verify_after_install is False
        assert config.auto_chmod is False
        assert config.use_exact_flag is False

    def test_load_config_creates_default_if_missing(self, tmp_path: Path) -> None:
        """Test that load_config creates default config if file doesn't exist."""
        config_file = tmp_path / "nonexistent.toml"

        config = load_config(config_file)

        assert isinstance(config, Config)
        # Should have default values
        assert config.clone_depth == 1
        assert config.auto_symlink is True

    def test_load_config_with_custom_path(self, tmp_path: Path) -> None:
        """Test that custom path parameter is respected."""
        custom_file = tmp_path / "custom.toml"
        custom_file.write_text(
            f"""
[global.paths]
repo_dir = "{tmp_path / "custom-repos"}"
install_dir = "{tmp_path / "custom-bin"}"
state_file = "{tmp_path / "custom-state.json"}"
""",
            encoding="utf-8",
        )

        config = load_config(custom_file)

        assert config.repo_dir == tmp_path / "custom-repos"
        assert config.install_dir == tmp_path / "custom-bin"

    def test_load_config_handles_partial_config(self, tmp_path: Path) -> None:
        """Test that missing fields use default values."""
        config_file = tmp_path / "partial.toml"
        config_file.write_text(
            f"""
[global.paths]
repo_dir = "{tmp_path / "repos"}"
install_dir = "{tmp_path / "bin"}"
state_file = "{tmp_path / "state.json"}"

[global.git]
clone_depth = 10
""",
            encoding="utf-8",
        )

        config = load_config(config_file)

        # Specified values
        assert config.clone_depth == 10
        # Default values for missing fields
        assert config.auto_symlink is True
        assert config.verify_after_install is True
        assert config.auto_chmod is True
        assert config.use_exact_flag is True

    def test_load_config_invalid_toml(self, tmp_path: Path) -> None:
        """Test that invalid TOML raises appropriate error."""
        config_file = tmp_path / "invalid.toml"
        config_file.write_text("this is not valid TOML [[[", encoding="utf-8")

        with pytest.raises(tomllib.TOMLDecodeError):
            load_config(config_file)

    def test_load_config_saves_default(self, tmp_path: Path) -> None:
        """Test that missing config is created by copying repository template."""
        config_file = tmp_path / "new-config.toml"
        assert not config_file.exists()

        load_config(config_file)

        assert config_file.exists()
        assert config_file.read_text(encoding="utf-8") == DEFAULT_CONFIG_TEMPLATE_PATH.read_text(
            encoding="utf-8"
        )

    def test_load_config_handles_permission_error(self, tmp_path: Path, monkeypatch) -> None:
        """Test graceful handling when unable to copy default config."""
        config_file = tmp_path / "readonly.toml"

        def mock_copy(path: Path) -> None:
            raise PermissionError("Read-only filesystem")

        monkeypatch.setattr("uv_helper.config._copy_default_config", mock_copy)

        config = load_config(config_file)

        assert isinstance(config, Config)
        assert not config_file.exists()

    def test_load_config_expands_paths_in_toml(self, tmp_path: Path) -> None:
        """Test that paths in TOML with ~ are expanded."""
        config_file = tmp_path / "config.toml"
        config_file.write_text(
            """
[global.paths]
repo_dir = "~/.local/share/uv-helper"
install_dir = "~/.local/bin"
state_file = "~/.local/share/uv-helper/state.json"
""",
            encoding="utf-8",
        )

        config = load_config(config_file)

        assert "~" not in str(config.repo_dir)
        assert "~" not in str(config.install_dir)
        assert "~" not in str(config.state_file)
        assert config.repo_dir.is_absolute()
