"""Configuration management for UV-Helper."""

import logging
import os
import shutil
import tomllib
from pathlib import Path
from typing import Any, Callable

import tomli_w
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .utils import ensure_dir, expand_path

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_TEMPLATE_PATH = Path(__file__).with_name("config.toml")
CURRENT_CONFIG_SCHEMA_VERSION = 1


def _load_default_template() -> dict[str, Any]:
    """Load the repository default config template."""
    with open(DEFAULT_CONFIG_TEMPLATE_PATH, "rb") as f:
        return tomllib.load(f)


def _merge_config_data(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Merge config dictionaries recursively."""
    merged = dict(base)
    for key, value in override.items():
        base_value = merged.get(key)
        if isinstance(base_value, dict) and isinstance(value, dict):
            merged[key] = _merge_config_data(base_value, value)
        else:
            merged[key] = value
    return merged


def _copy_default_config(config_path: Path) -> None:
    """Copy repository template to the user config path."""
    ensure_dir(config_path.parent)
    shutil.copyfile(DEFAULT_CONFIG_TEMPLATE_PATH, config_path)


def _migration_001_nested_layout(data: dict[str, Any]) -> dict[str, Any]:
    """Migration #1: Move legacy top-level sections into nested layout."""
    migrated = dict(data)

    legacy_paths = migrated.pop("paths", None)
    legacy_git = migrated.pop("git", None)
    legacy_install = migrated.pop("install", None)
    legacy_display = migrated.pop("display", None)

    legacy_mapped: dict[str, Any] = {}

    if isinstance(legacy_paths, dict):
        legacy_mapped.setdefault("global", {}).setdefault("paths", {}).update(legacy_paths)

    if isinstance(legacy_git, dict):
        legacy_mapped.setdefault("global", {}).setdefault("git", {}).update(legacy_git)

    if isinstance(legacy_install, dict):
        legacy_mapped.setdefault("global", {}).setdefault("install", {}).update(legacy_install)

    if isinstance(legacy_display, dict):
        list_section = legacy_mapped.setdefault("commands", {}).setdefault("list", {})

        if "list_verbose_fallback_on_narrow_width" in legacy_display:
            list_section["verbose_fallback"] = legacy_display["list_verbose_fallback_on_narrow_width"]

        if "list_min_width" in legacy_display:
            list_section["min_width"] = legacy_display["list_min_width"]

    # If both legacy and new keys are present, keep the new layout values.
    return _merge_config_data(legacy_mapped, migrated)


CONFIG_MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {
    1: _migration_001_nested_layout,
}


def _get_config_schema_version(data: dict[str, Any]) -> int:
    """Get config schema version from metadata section."""
    meta = data.get("meta")
    if not isinstance(meta, dict):
        return 0

    version = meta.get("schema_version", 0)
    if isinstance(version, int) and version >= 0:
        return version

    return 0


def _set_config_schema_version(data: dict[str, Any], version: int) -> None:
    """Set config schema version in metadata section."""
    meta = data.get("meta")
    if not isinstance(meta, dict):
        meta = {}
        data["meta"] = meta
    meta["schema_version"] = version


def _run_config_migrations(data: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Run pending config migrations based on schema version."""
    current_version = _get_config_schema_version(data)
    if current_version >= CURRENT_CONFIG_SCHEMA_VERSION:
        return data, False

    migrated = dict(data)

    for version in range(current_version + 1, CURRENT_CONFIG_SCHEMA_VERSION + 1):
        migration = CONFIG_MIGRATIONS.get(version)
        if migration is not None:
            migrated = migration(migrated)
        _set_config_schema_version(migrated, version)

    return migrated, True


def _save_config(config_path: Path, data: dict[str, Any]) -> None:
    """Persist config data to disk."""
    ensure_dir(config_path.parent)
    with open(config_path, "wb") as f:
        tomli_w.dump(data, f)


class GlobalPathsConfig(BaseModel):
    """Global path configuration."""

    repo_dir: Path
    install_dir: Path
    state_file: Path

    @field_validator("repo_dir", "install_dir", "state_file", mode="before")
    @classmethod
    def expand_paths(cls, v: str | Path) -> Path:
        """Expand path strings with ~ and environment variables."""
        if isinstance(v, str):
            return expand_path(v)
        return v


class GlobalGitConfig(BaseModel):
    """Global git configuration."""

    clone_depth: int = Field(default=1, ge=1, description="Git clone depth (must be >= 1)")


class GlobalInstallConfig(BaseModel):
    """Global install configuration."""

    auto_symlink: bool = True
    verify_after_install: bool = True
    auto_chmod: bool = True
    use_exact_flag: bool = True


class GlobalConfig(BaseModel):
    """Global configuration section."""

    paths: GlobalPathsConfig
    git: GlobalGitConfig
    install: GlobalInstallConfig


class ListCommandConfig(BaseModel):
    """List command configuration."""

    pass


class CommandsConfig(BaseModel):
    """Commands configuration section."""

    list: ListCommandConfig


class MetaConfig(BaseModel):
    """Configuration metadata section."""

    schema_version: int = Field(default=CURRENT_CONFIG_SCHEMA_VERSION, ge=0)


class Config(BaseModel):
    """Configuration for UV-Helper."""

    model_config = ConfigDict(arbitrary_types_allowed=True, populate_by_name=True)

    meta: MetaConfig = Field(default_factory=MetaConfig)
    global_config: GlobalConfig = Field(alias="global")
    commands: CommandsConfig

    @property
    def repo_dir(self) -> Path:
        """Repository storage directory."""
        return self.global_config.paths.repo_dir

    @property
    def install_dir(self) -> Path:
        """Directory for script symlinks."""
        return self.global_config.paths.install_dir

    @property
    def state_file(self) -> Path:
        """Path to state file."""
        return self.global_config.paths.state_file

    @property
    def clone_depth(self) -> int:
        """Git clone depth."""
        return self.global_config.git.clone_depth

    @property
    def auto_symlink(self) -> bool:
        """Whether symlinks are created automatically."""
        return self.global_config.install.auto_symlink

    @property
    def verify_after_install(self) -> bool:
        """Whether installed scripts are verified."""
        return self.global_config.install.verify_after_install

    @property
    def auto_chmod(self) -> bool:
        """Whether execute bits are set after install."""
        return self.global_config.install.auto_chmod

    @property
    def use_exact_flag(self) -> bool:
        """Whether --exact is used in shebangs by default."""
        return self.global_config.install.use_exact_flag

    @property
    def schema_version(self) -> int:
        """Config schema version."""
        return self.meta.schema_version


def get_config_path() -> Path:
    """
    Get configuration file path.

    Priority:
    1. UV_HELPER_CONFIG environment variable
    2. Default: ~/.config/uv-helper/config.toml

    Returns:
        Path to config file
    """
    env_config = os.environ.get("UV_HELPER_CONFIG")
    if env_config:
        return expand_path(env_config)

    return expand_path("~/.config/uv-helper/config.toml")


def create_default_config() -> Config:
    """Create default configuration from repository template."""
    return Config.model_validate(_load_default_template())


def load_config(config_path: Path | None = None) -> Config:
    """
    Load configuration from TOML file using Pydantic validation.

    Args:
        config_path: Optional custom config path

    Returns:
        Config instance with validated values

    Raises:
        ValueError: If config validation fails
    """
    if config_path is None:
        config_path = get_config_path()

    defaults = _load_default_template()

    if not config_path.exists():
        try:
            _copy_default_config(config_path)
        except (OSError, PermissionError) as e:
            logger.warning(f"Could not copy default config to {config_path}: {e}")

    if config_path.exists():
        with open(config_path, "rb") as f:
            data = tomllib.load(f)

        data, was_migrated = _run_config_migrations(data)
        if was_migrated:
            try:
                _save_config(config_path, data)
            except (OSError, PermissionError) as e:
                logger.warning(f"Could not save migrated config to {config_path}: {e}")

        merged_values = _merge_config_data(defaults, data)
        return Config.model_validate(merged_values)

    return Config.model_validate(defaults)
