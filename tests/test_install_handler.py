"""Tests for InstallHandler branch coverage and behavior."""

from datetime import datetime
from pathlib import Path

import pytest
from rich.console import Console

from uv_helper.commands.install import (
    InstallationContext,
    InstallHandler,
    InstallRequest,
    ScriptInstallOptions,
)
from uv_helper.config import load_config
from uv_helper.constants import SourceType
from uv_helper.git_manager import GitRef
from uv_helper.script_installer import ScriptInstallerError
from uv_helper.state import ScriptInfo


def _write_config(
    config_path: Path,
    repo_dir: Path,
    install_dir: Path,
    state_file: Path,
) -> None:
    config_path.write_text(
        "\n".join(
            [
                "[global.paths]",
                f'repo_dir = "{repo_dir}"',
                f'install_dir = "{install_dir}"',
                f'state_file = "{state_file}"',
                "",
                "[global.git]",
                "clone_depth = 1",
                "",
                "[global.install]",
                "auto_symlink = true",
                "verify_after_install = true",
                "auto_chmod = true",
                "use_exact_flag = true",
            ]
        ),
        encoding="utf-8",
    )


def _build_handler(tmp_path: Path) -> tuple[InstallHandler, Path, Path, Path, Path]:
    repo_dir = tmp_path / "repos"
    install_dir = tmp_path / "bin"
    state_file = tmp_path / "state.json"
    config_path = tmp_path / "config.toml"
    _write_config(config_path, repo_dir, install_dir, state_file)
    config = load_config(config_path)
    handler = InstallHandler(config, Console(record=True))
    return handler, repo_dir, install_dir, state_file, config_path


def test_install_returns_empty_when_existing_and_user_declines(tmp_path: Path, monkeypatch) -> None:
    """install should cancel when script already exists and overwrite is declined."""
    handler, repo_dir, _install_dir, _state_file, _config_path = _build_handler(tmp_path)

    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "tool.py").write_text("print('hello')\n", encoding="utf-8")

    handler.state_manager.add_script(
        ScriptInfo(
            name="tool.py",
            source_type=SourceType.LOCAL,
            installed_at=datetime.now(),
            repo_path=repo_dir / "tool",
            source_path=source_dir,
        )
    )

    monkeypatch.setattr("uv_helper.commands.install.prompt_confirm", lambda *args, **kwargs: False)

    request = InstallRequest(
        with_deps=None,
        force=False,
        no_symlink=True,
        install_dir=None,
        verbose=False,
        exact=None,
        copy_parent_dir=False,
        add_source_package=None,
        alias=None,
        no_deps=True,
    )
    results = handler.install(str(source_dir), ("tool.py",), request)

    assert results == []


def test_handle_local_source_raises_for_missing_and_non_directory(tmp_path: Path) -> None:
    """Local source helper should raise for missing paths and regular files."""
    handler, _repo_dir, _install_dir, _state_file, _config_path = _build_handler(tmp_path)

    with pytest.raises(FileNotFoundError):
        handler._handle_local_source(str(tmp_path / "missing"), ("tool.py",), copy_parent_dir=False)

    not_dir = tmp_path / "file.txt"
    not_dir.write_text("x", encoding="utf-8")
    with pytest.raises(NotADirectoryError):
        handler._handle_local_source(str(not_dir), ("tool.py",), copy_parent_dir=False)


def test_copy_and_create_directory_warn_when_target_exists(tmp_path: Path) -> None:
    """Directory creation helpers should print overwrite warnings when target exists."""
    handler, repo_dir, _install_dir, _state_file, _config_path = _build_handler(tmp_path)

    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "tool.py").write_text("print('x')\n", encoding="utf-8")

    # Existing target for copy-parent-dir path.
    (repo_dir / source_dir.name).mkdir(parents=True, exist_ok=True)
    handler._copy_parent_directory(source_dir)

    # Existing target for single-script directory path.
    (repo_dir / "tool").mkdir(parents=True, exist_ok=True)
    handler._create_script_directory("tool.py")

    output = handler.console.export_text()
    assert "Directory already exists" in output
    assert "Existing files will be overwritten" in output


def test_install_no_deps_verbose_prints_skip_message(tmp_path: Path, monkeypatch) -> None:
    """install should print skip message when --no-deps is used with verbose output."""
    handler, repo_dir, _install_dir, _state_file, _config_path = _build_handler(tmp_path)

    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "tool.py").write_text("print('x')\n", encoding="utf-8")

    monkeypatch.setattr(handler, "_install_scripts", lambda scripts, context, options: [])

    request = InstallRequest(
        with_deps=None,
        force=True,
        no_symlink=True,
        install_dir=None,
        verbose=True,
        exact=None,
        copy_parent_dir=False,
        add_source_package=None,
        alias=None,
        no_deps=True,
    )
    handler.install(str(source_dir), ("tool.py",), request)

    output = handler.console.export_text()
    assert "Skipping dependency resolution (--no-deps)" in output
    assert repo_dir.exists()


def test_resolve_dependencies_prints_and_reraises_errors(tmp_path: Path, monkeypatch) -> None:
    """Dependency resolver helper should surface and log file errors."""
    handler, repo_dir, _install_dir, _state_file, _config_path = _build_handler(tmp_path)

    def raise_missing(with_deps, repo_path, source_path):
        raise FileNotFoundError("missing requirements")

    monkeypatch.setattr("uv_helper.commands.install.resolve_dependencies", raise_missing)

    with pytest.raises(FileNotFoundError, match="missing requirements"):
        handler._resolve_dependencies("requirements.txt", repo_dir, None, verbose=True)

    assert "Dependencies: missing requirements" in handler.console.export_text()


def test_install_single_script_invalid_and_missing_paths(tmp_path: Path) -> None:
    """_install_single_script should reject invalid names and report missing scripts."""
    handler, repo_dir, install_dir, _state_file, _config_path = _build_handler(tmp_path)

    source_dir = tmp_path / "source"
    source_dir.mkdir()

    local_context = InstallationContext(
        repo_path=repo_dir / "tool",
        source_path=source_dir,
        is_local=True,
        is_git=False,
        copy_parent_dir=False,
        commit_hash=None,
        actual_ref=None,
        git_ref=None,
    )
    options = ScriptInstallOptions(
        dependencies=[],
        install_directory=install_dir,
        no_symlink=True,
        exact=None,
        add_source_package=None,
        alias=None,
    )

    invalid = handler._install_single_script("bad\x00.py", local_context, options)
    missing_local = handler._install_single_script("missing.py", local_context, options)

    git_context = InstallationContext(
        repo_path=repo_dir / "git-repo",
        source_path=None,
        is_local=False,
        is_git=True,
        copy_parent_dir=False,
        commit_hash="abc12345",
        actual_ref="main",
        git_ref=GitRef(base_url="https://github.com/acme/repo", ref_type="branch", ref_value="main"),
    )
    missing_git = handler._install_single_script("missing.py", git_context, options)

    assert invalid[1] is False and "Invalid script name" in str(invalid[2])
    assert missing_local == ("missing.py", False, "Not found")
    assert missing_git == ("missing.py", False, "Not found")


def test_install_single_script_git_success_warns_and_handles_installer_error(
    tmp_path: Path, monkeypatch
) -> None:
    """Git script installation should store state, print warnings, and handle install errors."""
    handler, repo_dir, install_dir, _state_file, _config_path = _build_handler(tmp_path)

    repo_path = repo_dir / "git-repo"
    repo_path.mkdir(parents=True)
    script_path = repo_path / "tool.py"
    script_path.write_text("print('ok')\n", encoding="utf-8")

    context = InstallationContext(
        repo_path=repo_path,
        source_path=None,
        is_local=False,
        is_git=True,
        copy_parent_dir=False,
        commit_hash="deadbeef",
        actual_ref="main",
        git_ref=GitRef(base_url="https://github.com/acme/repo", ref_type="branch", ref_value="main"),
    )
    options = ScriptInstallOptions(
        dependencies=["requests"],
        install_directory=install_dir,
        no_symlink=False,
        exact=True,
        add_source_package="",
        alias="short",
    )

    monkeypatch.setattr("uv_helper.commands.install.add_package_source", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "uv_helper.commands.install.install_script",
        lambda script_path, deps, install_config: (install_dir / "short", "shadows existing command"),
    )

    success = handler._install_single_script("tool.py", context, options)
    saved = handler.state_manager.get_script("tool.py")

    assert success[0] == "tool.py"
    assert success[1] is True
    assert saved is not None
    assert saved.source_type == SourceType.GIT
    assert saved.source_url == "https://github.com/acme/repo"
    assert "git-repo" in saved.dependencies
    assert "shadows existing command" in handler.console.export_text()

    monkeypatch.setattr(
        "uv_helper.commands.install.install_script",
        lambda *args, **kwargs: (_ for _ in ()).throw(ScriptInstallerError("install failed")),
    )
    failure = handler._install_single_script("tool.py", context, options)
    assert failure == ("tool.py", False, "install failed")
