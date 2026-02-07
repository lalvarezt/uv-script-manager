"""Tests for UpdateHandler behavior and edge branches."""

from datetime import datetime
from pathlib import Path
from typing import cast

import pytest
from rich.console import Console

from uv_helper.commands.update import UpdateHandler
from uv_helper.config import load_config
from uv_helper.constants import SourceType
from uv_helper.git_manager import GitError
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


def _build_handler(tmp_path: Path) -> tuple[UpdateHandler, Path, Path]:
    repo_dir = tmp_path / "repos"
    install_dir = tmp_path / "bin"
    state_file = tmp_path / "state.json"
    config_path = tmp_path / "config.toml"
    _write_config(config_path, repo_dir, install_dir, state_file)
    config = load_config(config_path)
    return UpdateHandler(config, Console(record=True)), repo_dir, install_dir


def _add_git_script(
    handler: UpdateHandler,
    repo_path: Path,
    symlink_path: Path | None = None,
    name: str = "tool.py",
) -> None:
    handler.state_manager.add_script(
        ScriptInfo(
            name=name,
            source_type=SourceType.GIT,
            source_url="https://github.com/acme/repo",
            ref="main",
            ref_type="branch",
            installed_at=datetime.now(),
            repo_path=repo_path,
            symlink_path=symlink_path,
            dependencies=["requests"],
            commit_hash="abc12345",
        )
    )


def _add_local_script(
    handler: UpdateHandler,
    repo_path: Path,
    source_path: Path,
    name: str = "tool.py",
) -> None:
    handler.state_manager.add_script(
        ScriptInfo(
            name=name,
            source_type=SourceType.LOCAL,
            installed_at=datetime.now(),
            repo_path=repo_path,
            source_path=source_path,
            dependencies=["requests"],
        )
    )


def test_update_dry_run_git_returns_status_and_local_changes_label(tmp_path: Path, monkeypatch) -> None:
    """Dry-run git update should return status and formatted local-change label."""
    handler, repo_dir, _install_dir = _build_handler(tmp_path)
    _add_git_script(handler, repo_dir / "repo")

    monkeypatch.setattr("uv_helper.commands.update.verify_git_available", lambda: True)
    monkeypatch.setattr("uv_helper.commands.update.get_local_change_state", lambda *args, **kwargs: "managed")
    monkeypatch.setattr(
        handler,
        "_check_git_script_update_status",
        lambda script_info, force, refresh_deps, local_change_state=None: "would update",
    )

    result = handler.update("tool.py", force=False, exact=None, refresh_deps=False, dry_run=True)

    assert result == ("tool.py", "would update", "No (managed)")


def test_update_all_collects_errors_for_dry_and_apply_modes(tmp_path: Path, monkeypatch) -> None:
    """update_all should collect errors without aborting run in both modes."""
    handler, repo_dir, _install_dir = _build_handler(tmp_path)
    _add_local_script(handler, repo_dir / "local", tmp_path / "source", name="local.py")
    _add_git_script(handler, repo_dir / "git", name="git.py")

    monkeypatch.setattr("uv_helper.commands.update.verify_git_available", lambda: True)
    monkeypatch.setattr("uv_helper.commands.update.get_local_change_state", lambda *args, **kwargs: "clean")
    monkeypatch.setattr(
        handler,
        "_check_git_script_update_status",
        lambda script_info, force, refresh_deps, local_change_state=None: (_ for _ in ()).throw(
            GitError("dry boom")
        ),
    )

    dry_results = handler.update_all(False, None, dry_run=True)
    assert any(item[1] == "skipped (local)" for item in dry_results)
    dry_error_found = False
    for row in dry_results:
        if len(row) == 3:
            _script_name, status, local_changes = cast(tuple[str, str, str], row)
            if status == "Error: dry boom" and local_changes == "Unknown":
                dry_error_found = True
                break
    assert dry_error_found

    monkeypatch.setattr(
        handler,
        "_update_git_script_internal",
        lambda script_info, force, exact, refresh_deps=False: (_ for _ in ()).throw(
            ScriptInstallerError("apply boom")
        ),
    )

    apply_results = handler.update_all(False, None, dry_run=False)
    assert any(item[1] == "skipped (local)" for item in apply_results)
    assert any(item[1] == "Error: apply boom" for item in apply_results if len(item) == 2)


def test_update_local_missing_source_raises_file_not_found(tmp_path: Path) -> None:
    """Local update should fail when original source directory no longer exists."""
    handler, repo_dir, _install_dir = _build_handler(tmp_path)
    _add_local_script(handler, repo_dir / "local", tmp_path / "missing-source")

    with pytest.raises(FileNotFoundError):
        handler.update("tool.py", force=False, exact=None, refresh_deps=False, dry_run=False)


def test_update_local_script_refreshes_dependencies_and_prints_shadow_warning(
    tmp_path: Path, monkeypatch
) -> None:
    """Local update should refresh deps, preserve alias, and print shadow warning."""
    handler, repo_dir, install_dir = _build_handler(tmp_path)

    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "tool.py").write_text("print('from source')\n", encoding="utf-8")

    repo_path = repo_dir / "local-repo"
    repo_path.mkdir(parents=True)
    (repo_path / "tool.py").write_text("print('old')\n", encoding="utf-8")

    script_info = ScriptInfo(
        name="tool.py",
        source_type=SourceType.LOCAL,
        installed_at=datetime.now(),
        repo_path=repo_path,
        symlink_path=install_dir / "short",
        dependencies=["requests"],
        source_path=source_dir,
    )

    install_alias_seen: dict[str, str | None] = {"value": None}

    def fake_install_script(script_path, dependencies, install_config):
        install_alias_seen["value"] = install_config.script_alias
        return install_dir / "short", "shadows existing command"

    monkeypatch.setattr("uv_helper.commands.update.resolve_dependencies", lambda *args, **kwargs: ["click"])
    monkeypatch.setattr("uv_helper.commands.update.install_script", fake_install_script)

    result = handler._update_local_script(script_info, exact=True, refresh_deps=True)

    assert result == ("short", "updated")
    assert script_info.dependencies == ["click"]
    assert install_alias_seen["value"] == "short"
    output = handler.console.export_text()
    assert "Dependencies refreshed:" in output
    assert "Warning:" in output


def test_update_local_script_returns_error_tuple_on_install_failure(tmp_path: Path, monkeypatch) -> None:
    """Local update should return error status when reinstall step fails."""
    handler, repo_dir, _install_dir = _build_handler(tmp_path)

    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "tool.py").write_text("print('x')\n", encoding="utf-8")

    repo_path = repo_dir / "local"
    repo_path.mkdir(parents=True)
    (repo_path / "tool.py").write_text("print('y')\n", encoding="utf-8")

    script_info = ScriptInfo(
        name="tool.py",
        source_type=SourceType.LOCAL,
        installed_at=datetime.now(),
        repo_path=repo_path,
        source_path=source_dir,
    )

    monkeypatch.setattr(
        "uv_helper.commands.update.install_script",
        lambda *args, **kwargs: (_ for _ in ()).throw(ScriptInstallerError("install failed")),
    )

    result = handler._update_local_script(script_info, exact=None, refresh_deps=False)
    assert result == ("tool.py", "Error: install failed")


def test_update_git_script_returns_error_tuple_when_internal_update_fails(
    tmp_path: Path, monkeypatch
) -> None:
    """Git update wrapper should convert internal exceptions to status tuple."""
    handler, repo_dir, _install_dir = _build_handler(tmp_path)
    _add_git_script(handler, repo_dir / "git")

    monkeypatch.setattr("uv_helper.commands.update.verify_git_available", lambda: True)
    monkeypatch.setattr(
        handler,
        "_update_git_script_internal",
        lambda *args, **kwargs: (_ for _ in ()).throw(GitError("git failed")),
    )

    script_info = handler.state_manager.get_script("tool.py")
    assert script_info is not None

    result = handler._update_git_script(script_info, force=False, exact=None, refresh_deps=False)
    assert result == ("tool.py", "Error: git failed")


def test_update_git_internal_up_to_date_and_local_change_guards(tmp_path: Path, monkeypatch) -> None:
    """Git internal updater should handle up-to-date and local-change guard branches."""
    handler, repo_dir, _install_dir = _build_handler(tmp_path)
    _add_git_script(handler, repo_dir / "git")
    script_info = handler.state_manager.get_script("tool.py")
    assert script_info is not None

    monkeypatch.setattr(
        "uv_helper.commands.update.get_remote_commit_hash", lambda *args, **kwargs: "abc12345"
    )
    assert (
        handler._update_git_script_internal(script_info, force=False, exact=None, refresh_deps=False)
        == "up-to-date"
    )

    monkeypatch.setattr(
        "uv_helper.commands.update.get_remote_commit_hash", lambda *args, **kwargs: "fffffff1"
    )
    monkeypatch.setattr(
        "uv_helper.commands.update.get_local_change_state", lambda *args, **kwargs: "blocking"
    )
    with pytest.raises(GitError, match="custom local changes"):
        handler._update_git_script_internal(script_info, force=False, exact=None, refresh_deps=False)

    monkeypatch.setattr("uv_helper.commands.update.get_local_change_state", lambda *args, **kwargs: "managed")
    monkeypatch.setattr(
        "uv_helper.commands.update.clear_managed_script_changes", lambda *args, **kwargs: False
    )
    with pytest.raises(GitError, match="Failed to clear uv-managed"):
        handler._update_git_script_internal(script_info, force=False, exact=None, refresh_deps=False)


def test_update_git_internal_fallback_branch_up_to_date_after_pull(tmp_path: Path, monkeypatch) -> None:
    """Git updater should fall back to stored ref when default branch lookup fails."""
    handler, repo_dir, _install_dir = _build_handler(tmp_path)
    _add_git_script(handler, repo_dir / "git")
    script_info = handler.state_manager.get_script("tool.py")
    assert script_info is not None

    monkeypatch.setattr(
        "uv_helper.commands.update.get_remote_commit_hash", lambda *args, **kwargs: "remote-new"
    )
    monkeypatch.setattr("uv_helper.commands.update.get_local_change_state", lambda *args, **kwargs: "clean")
    monkeypatch.setattr("uv_helper.commands.update.clone_or_update", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        "uv_helper.commands.update.get_current_commit_hash", lambda *args, **kwargs: "abc12345"
    )
    monkeypatch.setattr(
        "uv_helper.commands.update.get_default_branch",
        lambda *args, **kwargs: (_ for _ in ()).throw(GitError("detached")),
    )

    status = handler._update_git_script_internal(script_info, force=False, exact=None, refresh_deps=False)
    assert status == "up-to-date"
    assert script_info.ref == "main"


def test_update_git_internal_updates_state_with_alias_and_warning(tmp_path: Path, monkeypatch) -> None:
    """Git updater should preserve alias, emit warning, and persist updated commit/ref."""
    handler, repo_dir, install_dir = _build_handler(tmp_path)

    repo_path = repo_dir / "git"
    repo_path.mkdir(parents=True)
    (repo_path / "tool.py").write_text("print('ok')\n", encoding="utf-8")

    _add_git_script(handler, repo_path, symlink_path=install_dir / "short")
    script_info = handler.state_manager.get_script("tool.py")
    assert script_info is not None

    install_alias_seen: dict[str, str | None] = {"value": None}

    monkeypatch.setattr(
        "uv_helper.commands.update.get_remote_commit_hash", lambda *args, **kwargs: "remote-new"
    )
    monkeypatch.setattr("uv_helper.commands.update.get_local_change_state", lambda *args, **kwargs: "clean")
    monkeypatch.setattr("uv_helper.commands.update.clone_or_update", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        "uv_helper.commands.update.get_current_commit_hash", lambda *args, **kwargs: "fffffff1"
    )
    monkeypatch.setattr("uv_helper.commands.update.get_default_branch", lambda *args, **kwargs: "main")

    def fake_install(script_path, dependencies, install_config):
        install_alias_seen["value"] = install_config.script_alias
        return install_dir / "short", "shadow warning"

    monkeypatch.setattr("uv_helper.commands.update.install_script", fake_install)

    status = handler._update_git_script_internal(script_info, force=False, exact=True, refresh_deps=False)

    assert status == "updated"
    assert install_alias_seen["value"] == "short"
    assert script_info.commit_hash == "fffffff1"
    assert script_info.ref == "main"
    assert "Warning:" in handler.console.export_text()


def test_check_git_script_update_status_variants_and_label_formatting(tmp_path: Path, monkeypatch) -> None:
    """Status helper should cover pinned/up-to-date/local-change branches and label formatting."""
    handler, repo_dir, _install_dir = _build_handler(tmp_path)

    pinned = ScriptInfo(
        name="tagged.py",
        source_type=SourceType.GIT,
        source_url="https://github.com/acme/repo",
        ref="v1.2.3",
        ref_type="tag",
        installed_at=datetime.now(),
        repo_path=repo_dir / "tagged",
        commit_hash="11111111",
    )
    assert (
        handler._check_git_script_update_status(pinned, force=False, refresh_deps=False) == "pinned to v1.2.3"
    )

    branch = ScriptInfo(
        name="branch.py",
        source_type=SourceType.GIT,
        source_url="https://github.com/acme/repo",
        ref="main",
        ref_type="branch",
        installed_at=datetime.now(),
        repo_path=repo_dir / "branch",
        commit_hash="22222222",
    )
    monkeypatch.setattr(
        "uv_helper.commands.update.get_remote_commit_hash", lambda *args, **kwargs: "22222222"
    )
    assert handler._check_git_script_update_status(branch, force=False, refresh_deps=False) == "up-to-date"

    monkeypatch.setattr(
        "uv_helper.commands.update.get_remote_commit_hash", lambda *args, **kwargs: "33333333"
    )
    monkeypatch.setattr(
        "uv_helper.commands.update.get_local_change_state", lambda *args, **kwargs: "blocking"
    )
    assert (
        handler._check_git_script_update_status(
            branch, force=False, refresh_deps=False, local_change_state=None
        )
        == "would update (local custom changes present)"
    )

    assert handler._format_local_changes_label("clean") == "No"
