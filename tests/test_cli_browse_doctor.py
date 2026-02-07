"""CLI browse and doctor command integration tests."""

import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from click.testing import CliRunner

from tests.cli_helpers import REQUIRES_UV, _run_git, _write_config
from uv_helper.cli import cli
from uv_helper.constants import GIT_SHORT_HASH_LENGTH, SourceType
from uv_helper.git_manager import GitError
from uv_helper.script_installer import ScriptInstallerError
from uv_helper.state import ScriptInfo, StateManager


@REQUIRES_UV
def test_cli_doctor_detects_and_repairs_state_issues(tmp_path: Path) -> None:
    """Doctor should report issues and --repair should apply fixes."""
    runner = CliRunner()

    repo_dir = tmp_path / "repos"
    install_dir = tmp_path / "bin"
    state_file = tmp_path / "state.json"
    config_path = tmp_path / "config.toml"
    _write_config(config_path, repo_dir, install_dir, state_file)

    install_dir.mkdir(parents=True, exist_ok=True)
    state_manager = StateManager(state_file)

    missing_repo = tmp_path / "missing-repo"
    broken_repo = repo_dir / "broken-repo"
    broken_repo.mkdir(parents=True)
    (broken_repo / "broken.py").write_text("print('ok')\n", encoding="utf-8")

    broken_symlink = install_dir / "broken.py"
    broken_symlink.symlink_to(tmp_path / "missing-target.py")

    state_manager.add_script(
        ScriptInfo(
            name="missing.py",
            source_type=SourceType.LOCAL,
            installed_at=datetime.now(),
            repo_path=missing_repo,
            source_path=tmp_path,
            symlink_path=install_dir / "missing.py",
        )
    )
    state_manager.add_script(
        ScriptInfo(
            name="broken.py",
            source_type=SourceType.LOCAL,
            installed_at=datetime.now(),
            repo_path=broken_repo,
            source_path=tmp_path,
            symlink_path=broken_symlink,
        )
    )

    check_result = runner.invoke(cli, ["--config", str(config_path), "doctor"])

    assert check_result.exit_code == 0, check_result.output
    assert "Found" in check_result.output
    assert "doctor --repair" in check_result.output

    repair_result = runner.invoke(cli, ["--config", str(config_path), "doctor", "--repair"])

    assert repair_result.exit_code == 0, repair_result.output
    assert "Repair complete" in repair_result.output
    assert "Removed 1 broken symlink" in repair_result.output
    assert "Removed 1 missing script" in repair_result.output

    updated_state = StateManager(state_file)
    assert updated_state.get_script("missing.py") is None
    assert updated_state.get_script("broken.py") is not None
    assert not broken_symlink.exists()


def test_cli_browse_uses_github_api_when_available(tmp_path: Path, monkeypatch) -> None:
    """browse should use GitHub API listing when gh is available."""
    runner = CliRunner()

    repo_dir = tmp_path / "repos"
    install_dir = tmp_path / "bin"
    state_file = tmp_path / "state.json"
    config_path = tmp_path / "config.toml"
    _write_config(config_path, repo_dir, install_dir, state_file)

    monkeypatch.setattr("uv_helper.cli.verify_uv_available", lambda: True)

    real_which = shutil.which

    def fake_which(cmd: str) -> str | None:
        if cmd == "gh":
            return "/usr/bin/gh"
        return real_which(cmd)

    monkeypatch.setattr(shutil, "which", fake_which)

    def fake_subprocess_run(cmd, **kwargs):
        assert cmd[0] == "gh"
        assert cmd[1] == "api"
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout="app.py\npkg/tool.py\npkg/__init__.py\ntests/test_tool.py\n",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_subprocess_run)

    def fail_clone_or_update(*args, **kwargs):
        raise AssertionError("clone fallback should not run when GitHub API succeeds")

    monkeypatch.setattr("uv_helper.git_manager.clone_or_update", fail_clone_or_update)

    result = runner.invoke(
        cli,
        ["--config", str(config_path), "browse", "https://github.com/acme/repo#main"],
    )

    assert result.exit_code == 0, result.output
    assert "Fetching file list from GitHub API" in result.output
    assert "app.py" in result.output
    assert "tool.py" in result.output
    assert "__init__.py" not in result.output
    assert "test_tool.py" not in result.output
    assert "2 script(s) found" in result.output


def test_cli_browse_clone_fallback_respects_all_flag(tmp_path: Path, monkeypatch) -> None:
    """browse fallback should filter defaults and include extra files with --all."""
    import tempfile

    runner = CliRunner()

    repo_dir = tmp_path / "repos"
    install_dir = tmp_path / "bin"
    state_file = tmp_path / "state.json"
    config_path = tmp_path / "config.toml"
    _write_config(config_path, repo_dir, install_dir, state_file)

    monkeypatch.setattr("uv_helper.cli.verify_uv_available", lambda: True)
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))

    real_which = shutil.which

    def fake_which(cmd: str) -> str | None:
        if cmd == "gh":
            return None
        return real_which(cmd)

    monkeypatch.setattr(shutil, "which", fake_which)

    def fake_clone_or_update(url, ref, repo_path, depth=1, ref_type=None):
        repo_path.mkdir(parents=True, exist_ok=True)
        (repo_path / "app.py").write_text("print('app')\n", encoding="utf-8")
        (repo_path / "pkg").mkdir(exist_ok=True)
        (repo_path / "pkg" / "__init__.py").write_text("# init\n", encoding="utf-8")
        (repo_path / "tests").mkdir(exist_ok=True)
        (repo_path / "tests" / "test_tool.py").write_text("print('test')\n", encoding="utf-8")
        (repo_path / ".hidden").mkdir(exist_ok=True)
        (repo_path / ".hidden" / "secret.py").write_text("print('secret')\n", encoding="utf-8")

    monkeypatch.setattr("uv_helper.git_manager.clone_or_update", fake_clone_or_update)

    default_result = runner.invoke(
        cli,
        ["--config", str(config_path), "browse", "https://github.com/acme/repo"],
    )
    assert default_result.exit_code == 0, default_result.output
    assert "GitHub API unavailable, falling back to clone" in default_result.output
    assert "app.py" in default_result.output
    assert "__init__.py" not in default_result.output
    assert "test_tool.py" not in default_result.output
    assert "secret.py" not in default_result.output
    assert "1 script(s) found" in default_result.output

    all_result = runner.invoke(
        cli,
        ["--config", str(config_path), "browse", "https://github.com/acme/repo", "--all"],
    )
    assert all_result.exit_code == 0, all_result.output
    assert "Updating cached repository" in all_result.output
    assert "app.py" in all_result.output
    assert "__init__.py" in all_result.output
    assert "test_tool.py" in all_result.output
    assert "secret.py" not in all_result.output
    assert "3 script(s) found" in all_result.output


def test_cli_browse_error_branches_and_doctor_uv_missing(tmp_path: Path, monkeypatch) -> None:
    """browse should handle API and clone failures; doctor should report missing uv."""
    import tempfile

    runner = CliRunner()
    repo_dir = tmp_path / "repos"
    install_dir = tmp_path / "bin"
    state_file = tmp_path / "state.json"
    config_path = tmp_path / "config.toml"
    _write_config(config_path, repo_dir, install_dir, state_file)

    monkeypatch.setattr("uv_helper.cli.verify_uv_available", lambda: True)
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))

    real_which = shutil.which

    def gh_available(cmd: str) -> str | None:
        if cmd == "gh":
            return "/usr/bin/gh"
        return real_which(cmd)

    monkeypatch.setattr(shutil, "which", gh_available)

    def failing_gh(cmd, **kwargs):
        raise subprocess.CalledProcessError(1, cmd, stderr="gh failed")

    monkeypatch.setattr(subprocess, "run", failing_gh)

    def fallback_clone(url, ref, repo_path, depth=1, ref_type=None):
        repo_path.mkdir(parents=True, exist_ok=True)
        (repo_path / "__init__.py").write_text("# init\n", encoding="utf-8")
        (repo_path / "tests").mkdir(exist_ok=True)
        (repo_path / "tests" / "test_app.py").write_text("print('x')\n", encoding="utf-8")

    monkeypatch.setattr("uv_helper.git_manager.clone_or_update", fallback_clone)

    browse_no_scripts = runner.invoke(
        cli,
        ["--config", str(config_path), "browse", "https://github.com/acme/repo"],
    )
    assert browse_no_scripts.exit_code == 0, browse_no_scripts.output
    assert "GitHub API unavailable, falling back to clone" in browse_no_scripts.output
    assert "No Python scripts found." in browse_no_scripts.output

    monkeypatch.setattr(
        "uv_helper.git_manager.clone_or_update",
        lambda *args, **kwargs: (_ for _ in ()).throw(GitError("clone failed")),
    )
    browse_error = runner.invoke(
        cli,
        ["--config", str(config_path), "browse", "https://github.com/acme/repo"],
    )
    assert browse_error.exit_code != 0
    assert "Error:" in browse_error.output

    verify_calls = {"count": 0}

    def verify_uv_sequence() -> bool:
        verify_calls["count"] += 1
        if verify_calls["count"] == 1:
            return True
        raise ScriptInstallerError("uv missing")

    monkeypatch.setattr("uv_helper.cli.verify_uv_available", verify_uv_sequence)
    doctor_result = runner.invoke(cli, ["--config", str(config_path), "doctor"])
    assert doctor_result.exit_code == 0, doctor_result.output
    assert "uv (Python package manager):" in doctor_result.output
    assert "Not found" in doctor_result.output
    assert "No issues found - state is healthy" in doctor_result.output
