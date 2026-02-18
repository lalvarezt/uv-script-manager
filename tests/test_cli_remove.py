"""CLI remove command integration tests."""

from datetime import datetime
from pathlib import Path

from click.testing import CliRunner

from tests.cli_helpers import REQUIRES_UV, _write_config
from uv_script_manager.cli import cli
from uv_script_manager.constants import SourceType
from uv_script_manager.state import ScriptInfo, StateManager


def test_cli_remove_nonexistent_script(tmp_path: Path, monkeypatch) -> None:
    """Test that remove fails for nonexistent script."""
    runner = CliRunner()

    config_path = tmp_path / "config.toml"
    _write_config(config_path, tmp_path / "repos", tmp_path / "bin", tmp_path / "state.json")

    monkeypatch.setenv("UV_SCRIPT_MANAGER_CONFIG", str(config_path))
    monkeypatch.setattr("uv_script_manager.cli.verify_uv_available", lambda: True)

    result = runner.invoke(cli, ["remove", "nonexistent.py"])

    assert result.exit_code != 0
    assert "not found" in result.output.lower()


def test_cli_remove_clean_repo_prints_impact_summary(tmp_path: Path, monkeypatch) -> None:
    """remove --clean-repo should print a compact impact summary."""
    runner = CliRunner()

    repo_dir = tmp_path / "repos"
    install_dir = tmp_path / "bin"
    state_file = tmp_path / "state.json"
    config_path = tmp_path / "config.toml"
    _write_config(config_path, repo_dir, install_dir, state_file)

    monkeypatch.setenv("UV_SCRIPT_MANAGER_CONFIG", str(config_path))
    monkeypatch.setattr("uv_script_manager.cli.verify_uv_available", lambda: True)

    shared_repo = repo_dir / "shared"
    shared_repo.mkdir(parents=True)
    script_a = shared_repo / "a.py"
    script_b = shared_repo / "b.py"
    script_a.write_text("print('a')\n", encoding="utf-8")
    script_b.write_text("print('b')\n", encoding="utf-8")

    state_manager = StateManager(state_file)
    state_manager.add_script(
        ScriptInfo(
            name="a.py",
            source_type=SourceType.LOCAL,
            installed_at=datetime.now(),
            repo_path=shared_repo,
            source_path=tmp_path,
        )
    )
    state_manager.add_script(
        ScriptInfo(
            name="b.py",
            source_type=SourceType.LOCAL,
            installed_at=datetime.now(),
            repo_path=shared_repo,
            source_path=tmp_path,
        )
    )

    result = runner.invoke(
        cli,
        ["remove", "a.py", "--clean-repo", "--force"],
    )

    assert result.exit_code == 0, result.output
    assert "Impact:" in result.output
    assert "remove --clean-repo" in result.output
    assert "shared by 1 other script" in result.output


def test_cli_show_and_remove_dry_run_not_found_errors(tmp_path: Path, monkeypatch) -> None:
    """show/remove --dry-run should fail with explicit not-found errors."""
    runner = CliRunner()
    repo_dir = tmp_path / "repos"
    install_dir = tmp_path / "bin"
    state_file = tmp_path / "state.json"
    config_path = tmp_path / "config.toml"
    _write_config(config_path, repo_dir, install_dir, state_file)

    monkeypatch.setattr("uv_script_manager.cli.verify_uv_available", lambda: True)

    show_result = runner.invoke(cli, ["--config", str(config_path), "show", "missing.py"])
    remove_result = runner.invoke(
        cli,
        ["--config", str(config_path), "remove", "missing.py", "--dry-run"],
    )

    assert show_result.exit_code != 0
    assert "Script 'missing.py' not found" in show_result.output
    assert remove_result.exit_code != 0
    assert "Script 'missing.py' not found" in remove_result.output


def test_cli_remove_dry_run_git_shared_repo_reports_kept(tmp_path: Path, monkeypatch) -> None:
    """remove --dry-run --clean-repo should report shared repo as kept."""
    runner = CliRunner()
    repo_dir = tmp_path / "repos"
    install_dir = tmp_path / "bin"
    state_file = tmp_path / "state.json"
    config_path = tmp_path / "config.toml"
    _write_config(config_path, repo_dir, install_dir, state_file)

    monkeypatch.setattr("uv_script_manager.cli.verify_uv_available", lambda: True)

    shared_repo = repo_dir / "shared-repo"
    state_manager = StateManager(state_file)
    state_manager.add_script(
        ScriptInfo(
            name="a.py",
            source_type=SourceType.GIT,
            source_url="https://github.com/acme/repo",
            ref="main",
            ref_type="branch",
            installed_at=datetime.now(),
            repo_path=shared_repo,
        )
    )
    state_manager.add_script(
        ScriptInfo(
            name="b.py",
            source_type=SourceType.GIT,
            source_url="https://github.com/acme/repo",
            ref="main",
            ref_type="branch",
            installed_at=datetime.now(),
            repo_path=shared_repo,
        )
    )

    result = runner.invoke(
        cli,
        ["--config", str(config_path), "remove", "a.py", "--clean-repo", "--dry-run"],
    )

    assert result.exit_code == 0, result.output
    assert "Source: https://github.com/acme/repo" in result.output
    assert "Repository action: kept (shared by other scripts)" in result.output


@REQUIRES_UV
def test_cli_remove_clean_repo_only_after_last_script(tmp_path: Path) -> None:
    """--clean-repo should remove repository only when last script is removed."""
    runner = CliRunner()

    repo_dir = tmp_path / "repos"
    install_dir = tmp_path / "bin"
    state_file = tmp_path / "state.json"
    config_path = tmp_path / "config.toml"
    _write_config(config_path, repo_dir, install_dir, state_file)

    shared_repo = repo_dir / "shared"
    shared_repo.mkdir(parents=True)
    script_a = shared_repo / "a.py"
    script_b = shared_repo / "b.py"
    script_a.write_text("print('a')\n", encoding="utf-8")
    script_b.write_text("print('b')\n", encoding="utf-8")

    install_dir.mkdir(parents=True, exist_ok=True)
    symlink_a = install_dir / "a.py"
    symlink_b = install_dir / "b.py"
    symlink_a.symlink_to(script_a)
    symlink_b.symlink_to(script_b)

    state_manager = StateManager(state_file)
    state_manager.add_script(
        ScriptInfo(
            name="a.py",
            source_type=SourceType.LOCAL,
            installed_at=datetime.now(),
            repo_path=shared_repo,
            source_path=tmp_path,
            symlink_path=symlink_a,
        )
    )
    state_manager.add_script(
        ScriptInfo(
            name="b.py",
            source_type=SourceType.LOCAL,
            installed_at=datetime.now(),
            repo_path=shared_repo,
            source_path=tmp_path,
            symlink_path=symlink_b,
        )
    )

    first_remove = runner.invoke(
        cli,
        ["--config", str(config_path), "remove", "a.py", "--clean-repo", "--force"],
    )

    assert first_remove.exit_code == 0, first_remove.output
    assert shared_repo.exists()
    assert StateManager(state_file).get_script("a.py") is None
    assert StateManager(state_file).get_script("b.py") is not None

    second_remove = runner.invoke(
        cli,
        ["--config", str(config_path), "remove", "b.py", "--clean-repo", "--force"],
    )

    assert second_remove.exit_code == 0, second_remove.output
    assert not shared_repo.exists()
    assert StateManager(state_file).get_script("b.py") is None


@REQUIRES_UV
def test_cli_remove_dry_run_does_not_mutate_state(tmp_path: Path) -> None:
    """remove --dry-run should report actions without changing state or filesystem."""
    runner = CliRunner()

    repo_dir = tmp_path / "repos"
    install_dir = tmp_path / "bin"
    state_file = tmp_path / "state.json"
    config_path = tmp_path / "config.toml"
    _write_config(config_path, repo_dir, install_dir, state_file)

    script_repo = repo_dir / "tool-repo"
    script_repo.mkdir(parents=True)
    script_path = script_repo / "tool.py"
    script_path.write_text("print('hello')\n", encoding="utf-8")

    install_dir.mkdir(parents=True, exist_ok=True)
    symlink_path = install_dir / "tool.py"
    symlink_path.symlink_to(script_path)

    state_manager = StateManager(state_file)
    state_manager.add_script(
        ScriptInfo(
            name="tool.py",
            source_type=SourceType.LOCAL,
            installed_at=datetime.now(),
            repo_path=script_repo,
            source_path=tmp_path,
            symlink_path=symlink_path,
        )
    )

    result = runner.invoke(
        cli,
        ["--config", str(config_path), "remove", "tool.py", "--clean-repo", "--dry-run"],
    )

    assert result.exit_code == 0, result.output
    assert "Dry run:" in result.output
    assert "would remove" in result.output
    assert StateManager(state_file).get_script("tool.py") is not None
    assert symlink_path.exists()
    assert script_repo.exists()


def test_cli_remove_dry_run_without_symlink_uses_clear_label(tmp_path: Path, monkeypatch) -> None:
    """remove --dry-run should label missing symlink paths consistently."""
    runner = CliRunner()

    repo_dir = tmp_path / "repos"
    install_dir = tmp_path / "bin"
    state_file = tmp_path / "state.json"
    config_path = tmp_path / "config.toml"
    _write_config(config_path, repo_dir, install_dir, state_file)

    monkeypatch.setattr("uv_script_manager.cli.verify_uv_available", lambda: True)

    script_repo = repo_dir / "tool-repo"
    script_repo.mkdir(parents=True)
    script_path = script_repo / "tool.py"
    script_path.write_text("print('hello')\n", encoding="utf-8")

    state_manager = StateManager(state_file)
    state_manager.add_script(
        ScriptInfo(
            name="tool.py",
            source_type=SourceType.LOCAL,
            installed_at=datetime.now(),
            repo_path=script_repo,
            source_path=tmp_path,
            symlink_path=None,
        )
    )

    result = runner.invoke(
        cli,
        ["--config", str(config_path), "remove", "tool.py", "--dry-run"],
    )

    assert result.exit_code == 0, result.output
    assert "Symlink: Not symlinked" in result.output
