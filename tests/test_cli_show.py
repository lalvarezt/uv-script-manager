"""CLI show command integration tests."""

import json
from datetime import datetime
from pathlib import Path

from click.testing import CliRunner

from tests.cli_helpers import REQUIRES_GIT, REQUIRES_UV, _run_git, _write_config
from uv_helper.cli import cli
from uv_helper.constants import GIT_SHORT_HASH_LENGTH, SourceType
from uv_helper.state import ScriptInfo, StateManager


@REQUIRES_UV
def test_cli_show_displays_ref_and_commit_for_git_scripts(tmp_path: Path) -> None:
    """show should include Ref and Commit fields for git-backed scripts."""
    runner = CliRunner()

    repo_dir = tmp_path / "repos"
    install_dir = tmp_path / "bin"
    state_file = tmp_path / "state.json"
    config_path = tmp_path / "config.toml"
    _write_config(config_path, repo_dir, install_dir, state_file)

    state_manager = StateManager(state_file)
    state_manager.add_script(
        ScriptInfo(
            name="tool.py",
            source_type=SourceType.GIT,
            source_url="https://github.com/user/repo",
            ref="v2.0.0",
            ref_type="tag",
            installed_at=datetime.now(),
            repo_path=repo_dir / "user-repo",
            commit_hash="abc12345",
        )
    )

    result = runner.invoke(cli, ["--config", str(config_path), "show", "tool.py"])

    assert result.exit_code == 0, result.output
    assert "Ref:" in result.output
    assert "v2.0.0" in result.output
    assert "Commit:" in result.output
    assert "abc12345" in result.output


@REQUIRES_UV
@REQUIRES_GIT
def test_cli_show_displays_local_changes_for_git_scripts(tmp_path: Path) -> None:
    """show should display local uncommitted changes state for git scripts."""
    runner = CliRunner()

    repo_dir = tmp_path / "repos"
    install_dir = tmp_path / "bin"
    state_file = tmp_path / "state.json"
    config_path = tmp_path / "config.toml"
    _write_config(config_path, repo_dir, install_dir, state_file)

    script_repo = repo_dir / "tool-repo"
    script_repo.mkdir(parents=True)
    _run_git(script_repo, "init", "-b", "main")
    (script_repo / "tool.py").write_text("print('v1')\n", encoding="utf-8")
    _run_git(script_repo, "add", "tool.py")
    _run_git(
        script_repo,
        "-c",
        "user.name=Test User",
        "-c",
        "user.email=test@example.com",
        "commit",
        "-m",
        "initial",
    )
    commit_hash = _run_git(script_repo, "rev-parse", f"--short={GIT_SHORT_HASH_LENGTH}", "HEAD")

    (script_repo / "tool.py").write_text("print('dirty')\n", encoding="utf-8")

    state_manager = StateManager(state_file)
    state_manager.add_script(
        ScriptInfo(
            name="tool.py",
            source_type=SourceType.GIT,
            source_url="https://github.com/user/repo",
            ref="main",
            ref_type="branch",
            installed_at=datetime.now(),
            repo_path=script_repo,
            commit_hash=commit_hash,
        )
    )

    result = runner.invoke(cli, ["--config", str(config_path), "show", "tool.py"])

    assert result.exit_code == 0, result.output
    assert "Local changes:" in result.output
    assert "Needs attention" in result.output


def test_cli_show_json_outputs_parseable_payload(tmp_path: Path, monkeypatch) -> None:
    """show --json should emit script details as JSON."""
    runner = CliRunner()

    repo_dir = tmp_path / "repos"
    install_dir = tmp_path / "bin"
    state_file = tmp_path / "state.json"
    config_path = tmp_path / "config.toml"
    _write_config(config_path, repo_dir, install_dir, state_file)

    monkeypatch.setattr("uv_helper.cli.verify_uv_available", lambda: True)

    state_manager = StateManager(state_file)
    state_manager.add_script(
        ScriptInfo(
            name="tool.py",
            source_type=SourceType.LOCAL,
            installed_at=datetime.now(),
            repo_path=repo_dir / "tool-repo",
            source_path=tmp_path,
        )
    )

    result = runner.invoke(
        cli,
        ["--config", str(config_path), "show", "tool.py", "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["script"]["name"] == "tool.py"
    assert payload["script"]["status"] == "local"


@REQUIRES_UV
@REQUIRES_GIT
def test_cli_show_reports_uv_managed_changes_as_non_blocking(tmp_path: Path) -> None:
    """show should report uv-managed script changes as non-blocking local changes."""
    runner = CliRunner()

    repo_dir = tmp_path / "repos"
    install_dir = tmp_path / "bin"
    state_file = tmp_path / "state.json"
    config_path = tmp_path / "config.toml"
    _write_config(config_path, repo_dir, install_dir, state_file)

    script_repo = repo_dir / "tool-repo"
    script_repo.mkdir(parents=True)
    _run_git(script_repo, "init", "-b", "main")
    (script_repo / "tool.py").write_text("print('v1')\n", encoding="utf-8")
    _run_git(script_repo, "add", "tool.py")
    _run_git(
        script_repo,
        "-c",
        "user.name=Test User",
        "-c",
        "user.email=test@example.com",
        "commit",
        "-m",
        "initial",
    )
    commit_hash = _run_git(script_repo, "rev-parse", f"--short={GIT_SHORT_HASH_LENGTH}", "HEAD")

    (script_repo / "tool.py").write_text(
        "\n".join(
            [
                "#!/usr/bin/env -S uv run --exact --script",
                "# /// script",
                "# dependencies = [",
                '#     "requests",',
                "# ]",
                "# ///",
                "print('v1')",
                "",
            ]
        ),
        encoding="utf-8",
    )

    state_manager = StateManager(state_file)
    state_manager.add_script(
        ScriptInfo(
            name="tool.py",
            source_type=SourceType.GIT,
            source_url="https://github.com/user/repo",
            ref="main",
            ref_type="branch",
            installed_at=datetime.now(),
            repo_path=script_repo,
            commit_hash=commit_hash,
        )
    )

    result = runner.invoke(cli, ["--config", str(config_path), "show", "tool.py"])

    assert result.exit_code == 0, result.output
    assert "Local changes:" in result.output
    assert "Managed" in result.output
