"""CLI list command integration tests."""

import json
from datetime import datetime
from pathlib import Path

from click.testing import CliRunner
from rich.console import Console

from tests.cli_helpers import REQUIRES_GIT, REQUIRES_UV, _run_git, _write_config
from uv_helper.cli import cli
from uv_helper.constants import GIT_SHORT_HASH_LENGTH, SourceType
from uv_helper.state import ScriptInfo, StateManager


def test_cli_list_tree_verbose_groups_sources_and_aliases(tmp_path: Path, monkeypatch) -> None:
    """list --tree --verbose should include grouped sources and alias details."""
    runner = CliRunner()
    repo_dir = tmp_path / "repos"
    install_dir = tmp_path / "bin"
    state_file = tmp_path / "state.json"
    config_path = tmp_path / "config.toml"
    _write_config(config_path, repo_dir, install_dir, state_file)

    monkeypatch.setattr("uv_helper.cli.verify_uv_available", lambda: True)
    monkeypatch.setattr(
        "uv_helper.local_changes.get_local_change_state",
        lambda repo, name: "blocking" if name == "git_tool.py" else "managed",
    )

    state_manager = StateManager(state_file)
    state_manager.add_script(
        ScriptInfo(
            name="git_tool.py",
            source_type=SourceType.GIT,
            source_url="https://github.com/acme/repo",
            ref="main",
            ref_type="branch",
            installed_at=datetime.now(),
            repo_path=repo_dir / "git-repo",
            commit_hash="12345678",
            dependencies=["requests", "rich"],
            symlink_path=install_dir / "short",
        )
    )
    state_manager.add_script(
        ScriptInfo(
            name="local_tool.py",
            source_type=SourceType.LOCAL,
            installed_at=datetime.now(),
            repo_path=repo_dir / "local-repo",
            source_path=tmp_path / "src",
        )
    )

    result = runner.invoke(
        cli,
        ["--config", str(config_path), "list", "--tree", "--verbose"],
    )

    assert result.exit_code == 0, result.output
    assert "Installed Scripts by Source" in result.output
    assert "acme/repo" in result.output
    assert "short -> git_tool.py" in result.output
    assert "local changes: yes" in result.output
    assert "2 deps" in result.output


def test_cli_list_full_disables_truncation(tmp_path: Path, monkeypatch) -> None:
    """list --full should show untruncated values on narrow terminals."""
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
            dependencies=["verylongdependencyname_" * 5],
        )
    )

    narrow_result = runner.invoke(
        cli,
        ["--config", str(config_path), "list", "--verbose"],
        terminal_width=80,
    )
    full_result = runner.invoke(
        cli,
        ["--config", str(config_path), "list", "--verbose", "--full"],
        terminal_width=240,
    )

    assert narrow_result.exit_code == 0, narrow_result.output
    assert full_result.exit_code == 0, full_result.output
    assert "…" in narrow_result.output
    assert "…" not in full_result.output


def test_cli_list_full_changes_wide_verbose_output_for_long_values(tmp_path: Path, monkeypatch) -> None:
    """list --full should avoid ellipsis even on wide terminals with long values."""
    runner = CliRunner()

    repo_dir = tmp_path / "repos"
    install_dir = tmp_path / "bin"
    state_file = tmp_path / "state.json"
    config_path = tmp_path / "config.toml"
    _write_config(config_path, repo_dir, install_dir, state_file)

    monkeypatch.setattr("uv_helper.cli.verify_uv_available", lambda: True)
    monkeypatch.setattr("uv_helper.cli.console", Console(width=240))

    state_manager = StateManager(state_file)
    state_manager.add_script(
        ScriptInfo(
            name="tool.py",
            source_type=SourceType.LOCAL,
            installed_at=datetime.now(),
            repo_path=repo_dir / "tool-repo",
            source_path=Path("/very/long/source/path/that/keeps/going/on/for/a/while/for/testing/purposes"),
            dependencies=["verylongdependencyname_" * 5],
        )
    )

    verbose_result = runner.invoke(
        cli,
        ["--config", str(config_path), "list", "--verbose"],
    )
    full_result = runner.invoke(
        cli,
        ["--config", str(config_path), "list", "--verbose", "--full"],
    )

    assert verbose_result.exit_code == 0, verbose_result.output
    assert full_result.exit_code == 0, full_result.output
    assert "…" in verbose_result.output
    assert "…" not in full_result.output


def test_cli_list_filters_by_source_ref_and_status(tmp_path: Path, monkeypatch) -> None:
    """list should filter entries by source, ref, and status."""
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
            name="local.py",
            source_type=SourceType.LOCAL,
            installed_at=datetime.now(),
            repo_path=repo_dir / "local-repo",
            source_path=tmp_path / "local-src",
        )
    )
    state_manager.add_script(
        ScriptInfo(
            name="branch.py",
            source_type=SourceType.GIT,
            source_url="https://github.com/acme/repo-one",
            ref="main",
            ref_type="branch",
            installed_at=datetime.now(),
            repo_path=repo_dir / "branch-repo",
            commit_hash="11111111",
        )
    )
    state_manager.add_script(
        ScriptInfo(
            name="pinned.py",
            source_type=SourceType.GIT,
            source_url="https://github.com/acme/repo-two",
            ref="v1.2.3",
            ref_type="tag",
            installed_at=datetime.now(),
            repo_path=repo_dir / "pinned-repo",
            commit_hash="22222222",
        )
    )

    source_result = runner.invoke(
        cli,
        ["--config", str(config_path), "list", "--source", "repo-one"],
    )
    assert source_result.exit_code == 0, source_result.output
    assert "branch.py" in source_result.output
    assert "pinned.py" not in source_result.output

    ref_result = runner.invoke(
        cli,
        ["--config", str(config_path), "list", "--ref", "v1.2"],
    )
    assert ref_result.exit_code == 0, ref_result.output
    assert "pinned.py" in ref_result.output
    assert "branch.py" not in ref_result.output

    status_result = runner.invoke(
        cli,
        ["--config", str(config_path), "list", "--status", "pinned"],
    )
    assert status_result.exit_code == 0, status_result.output
    assert "pinned.py" in status_result.output
    assert "branch.py" not in status_result.output


def test_cli_list_sorts_by_updated_descending(tmp_path: Path, monkeypatch) -> None:
    """list --sort updated should show newest installs first."""
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
            name="older.py",
            source_type=SourceType.LOCAL,
            installed_at=datetime(2024, 1, 1, 0, 0, 0),
            repo_path=repo_dir / "older-repo",
            source_path=tmp_path,
        )
    )
    state_manager.add_script(
        ScriptInfo(
            name="newer.py",
            source_type=SourceType.LOCAL,
            installed_at=datetime(2025, 1, 1, 0, 0, 0),
            repo_path=repo_dir / "newer-repo",
            source_path=tmp_path,
        )
    )

    result = runner.invoke(
        cli,
        ["--config", str(config_path), "list", "--sort", "updated", "--full"],
    )

    assert result.exit_code == 0, result.output
    assert result.output.index("newer.py") < result.output.index("older.py")


def test_cli_list_shows_message_when_filters_match_nothing(tmp_path: Path, monkeypatch) -> None:
    """list should report when no scripts match filters."""
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
        ["--config", str(config_path), "list", "--status", "pinned"],
    )

    assert result.exit_code == 0, result.output
    assert "No scripts matched the provided filters." in result.output


def test_cli_list_json_outputs_parseable_payload(tmp_path: Path, monkeypatch) -> None:
    """list --json should emit structured JSON output."""
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
        ["--config", str(config_path), "list", "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert "scripts" in payload
    assert payload["scripts"][0]["name"] == "tool.py"
    assert payload["scripts"][0]["source_type"] == "local"


def test_cli_list_json_rejects_tree_mode(tmp_path: Path, monkeypatch) -> None:
    """list --json should reject --tree mode."""
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
        ["--config", str(config_path), "list", "--json", "--tree"],
    )

    assert result.exit_code != 0
    assert "cannot be combined" in result.output


@REQUIRES_UV
@REQUIRES_GIT
def test_cli_list_verbose_displays_local_changes_for_git_scripts(tmp_path: Path) -> None:
    """list --verbose should include local changes status for git scripts."""
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

    result = runner.invoke(
        cli,
        ["--config", str(config_path), "list", "--verbose"],
        terminal_width=180,
    )

    assert result.exit_code == 0, result.output
    assert "Local" in result.output
    assert "Needs atten" in result.output


@REQUIRES_UV
@REQUIRES_GIT
def test_cli_list_verbose_reports_uv_managed_changes_as_non_blocking(tmp_path: Path) -> None:
    """list --verbose should report uv-managed changes as non-blocking."""
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

    result = runner.invoke(
        cli,
        ["--config", str(config_path), "list", "--verbose"],
        terminal_width=180,
    )

    assert result.exit_code == 0, result.output
    assert "Local" in result.output
    assert "No" in result.output
    assert "manage" in result.output
