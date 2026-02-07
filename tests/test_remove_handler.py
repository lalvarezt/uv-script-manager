"""Tests for RemoveHandler behavior branches."""

from datetime import datetime
from pathlib import Path

import pytest
from rich.console import Console

from uv_helper.commands.remove import RemoveHandler
from uv_helper.config import load_config
from uv_helper.constants import SourceType
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


def _build_handler(tmp_path: Path) -> RemoveHandler:
    repo_dir = tmp_path / "repos"
    install_dir = tmp_path / "bin"
    state_file = tmp_path / "state.json"
    config_path = tmp_path / "config.toml"
    _write_config(config_path, repo_dir, install_dir, state_file)
    config = load_config(config_path)
    return RemoveHandler(config, Console(record=True))


def test_remove_non_force_git_prints_details_and_can_cancel(tmp_path: Path, monkeypatch) -> None:
    """Non-force removal should show source/symlink/repo details and allow cancellation."""
    handler = _build_handler(tmp_path)
    script_repo = tmp_path / "repos" / "git-repo"
    symlink = tmp_path / "bin" / "tool.py"

    handler.state_manager.add_script(
        ScriptInfo(
            name="tool.py",
            source_type=SourceType.GIT,
            source_url="https://github.com/acme/repo",
            ref="main",
            ref_type="branch",
            installed_at=datetime.now(),
            repo_path=script_repo,
            symlink_path=symlink,
        )
    )

    monkeypatch.setattr("uv_helper.commands.remove.prompt_confirm", lambda *args, **kwargs: False)

    handler.remove("tool.py", clean_repo=True, force=False)

    output = handler.console.export_text()
    assert "Source: https://github.com/acme/repo" in output
    assert "Repository:" in output
    assert "will be removed" in output
    assert "Removal cancelled." in output


def test_remove_re_raises_script_installer_error(tmp_path: Path, monkeypatch) -> None:
    """RemoveHandler should print and re-raise ScriptInstallerError from installer layer."""
    handler = _build_handler(tmp_path)

    handler.state_manager.add_script(
        ScriptInfo(
            name="tool.py",
            source_type=SourceType.LOCAL,
            installed_at=datetime.now(),
            repo_path=tmp_path / "repos" / "local-repo",
            source_path=tmp_path / "src",
        )
    )

    monkeypatch.setattr(
        "uv_helper.commands.remove.remove_script_installation",
        lambda *args, **kwargs: (_ for _ in ()).throw(ScriptInstallerError("remove failed")),
    )

    with pytest.raises(ScriptInstallerError, match="remove failed"):
        handler.remove("tool.py", clean_repo=False, force=True)

    assert "Error:" in handler.console.export_text()
