"""CLI update command integration tests."""

import json
import subprocess
from datetime import datetime
from pathlib import Path

from click.testing import CliRunner

from tests.cli_helpers import (
    REQUIRES_GIT,
    REQUIRES_UV,
    _create_origin_repo_with_tag,
    _run_git,
    _write_config,
)
from uv_script_manager.cli import cli
from uv_script_manager.constants import GIT_SHORT_HASH_LENGTH, SourceType
from uv_script_manager.state import ScriptInfo, StateManager


def test_cli_update_nonexistent_script(tmp_path: Path, monkeypatch) -> None:
    """Test that update fails for nonexistent script."""
    runner = CliRunner()

    config_path = tmp_path / "config.toml"
    _write_config(config_path, tmp_path / "repos", tmp_path / "bin", tmp_path / "state.json")

    monkeypatch.setenv("UV_SCRIPT_MANAGER_CONFIG", str(config_path))
    monkeypatch.setattr("uv_script_manager.cli.verify_uv_available", lambda: True)

    result = runner.invoke(cli, ["update", "nonexistent.py"])

    assert result.exit_code != 0
    assert "not found" in result.output.lower()


def test_cli_update_requires_script_name_or_all(tmp_path: Path, monkeypatch) -> None:
    """Update should require either SCRIPT_NAME or --all."""
    runner = CliRunner()

    config_path = tmp_path / "config.toml"
    _write_config(config_path, tmp_path / "repos", tmp_path / "bin", tmp_path / "state.json")

    monkeypatch.setenv("UV_SCRIPT_MANAGER_CONFIG", str(config_path))
    monkeypatch.setattr("uv_script_manager.cli.verify_uv_available", lambda: True)

    result = runner.invoke(cli, ["update"])

    assert result.exit_code != 0
    assert "Missing SCRIPT_NAME or --all" in result.output


def test_cli_update_rejects_script_name_with_all(tmp_path: Path, monkeypatch) -> None:
    """Update should reject SCRIPT_NAME when --all is provided."""
    runner = CliRunner()

    config_path = tmp_path / "config.toml"
    _write_config(config_path, tmp_path / "repos", tmp_path / "bin", tmp_path / "state.json")

    monkeypatch.setenv("UV_SCRIPT_MANAGER_CONFIG", str(config_path))
    monkeypatch.setattr("uv_script_manager.cli.verify_uv_available", lambda: True)

    result = runner.invoke(cli, ["update", "tool.py", "--all"])

    assert result.exit_code != 0
    assert "Cannot use SCRIPT_NAME and --all together" in result.output


def test_cli_update_all_prints_impact_summary(tmp_path: Path, monkeypatch) -> None:
    """update --all should print a compact impact summary."""
    runner = CliRunner()

    repo_dir = tmp_path / "repos"
    install_dir = tmp_path / "bin"
    state_file = tmp_path / "state.json"
    config_path = tmp_path / "config.toml"
    _write_config(config_path, repo_dir, install_dir, state_file)

    monkeypatch.setenv("UV_SCRIPT_MANAGER_CONFIG", str(config_path))
    monkeypatch.setattr("uv_script_manager.cli.verify_uv_available", lambda: True)

    state_manager = StateManager(state_file)
    state_manager.add_script(
        ScriptInfo(
            name="local.py",
            source_type=SourceType.LOCAL,
            installed_at=datetime.now(),
            repo_path=repo_dir / "local-repo",
            source_path=tmp_path,
        )
    )

    result = runner.invoke(cli, ["update", "--all", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "Impact:" in result.output
    assert "update --all" in result.output
    assert "Scripts: 1" in result.output
    assert "Mode: dry-run" in result.output


def test_cli_update_all_alias_is_hidden_but_still_available(tmp_path: Path, monkeypatch) -> None:
    """update-all should remain callable as a hidden compatibility alias."""
    runner = CliRunner()

    config_path = tmp_path / "config.toml"
    _write_config(config_path, tmp_path / "repos", tmp_path / "bin", tmp_path / "state.json")

    monkeypatch.setenv("UV_SCRIPT_MANAGER_CONFIG", str(config_path))
    monkeypatch.setattr("uv_script_manager.cli.verify_uv_available", lambda: True)

    help_result = runner.invoke(cli, ["--help"])
    assert help_result.exit_code == 0, help_result.output
    assert "update-all" not in help_result.output

    alias_result = runner.invoke(cli, ["update-all"])
    assert alias_result.exit_code == 0, alias_result.output
    assert "No scripts installed." in alias_result.output


def test_cli_update_all_dry_run_hides_local_changes_when_all_values_are_na(
    tmp_path: Path, monkeypatch
) -> None:
    """Dry-run update table should omit Local changes when every row is N/A."""
    runner = CliRunner()

    repo_dir = tmp_path / "repos"
    install_dir = tmp_path / "bin"
    state_file = tmp_path / "state.json"
    config_path = tmp_path / "config.toml"
    _write_config(config_path, repo_dir, install_dir, state_file)

    monkeypatch.setenv("UV_SCRIPT_MANAGER_CONFIG", str(config_path))
    monkeypatch.setattr("uv_script_manager.cli.verify_uv_available", lambda: True)

    state_manager = StateManager(state_file)
    state_manager.add_script(
        ScriptInfo(
            name="local.py",
            source_type=SourceType.LOCAL,
            installed_at=datetime.now(),
            repo_path=repo_dir / "local-repo",
            source_path=tmp_path,
        )
    )

    result = runner.invoke(cli, ["update", "--all", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "Skipped (local-only)" in result.output
    assert "Local changes" not in result.output


def test_cli_local_update_without_copy_parent_dir(tmp_path: Path, monkeypatch) -> None:
    """Test updating a local script installed without --copy-parent-dir."""
    runner = CliRunner()

    repo_dir = tmp_path / "repos"
    install_dir = tmp_path / "bin"
    state_file = tmp_path / "state.json"
    config_path = tmp_path / "config.toml"
    _write_config(config_path, repo_dir, install_dir, state_file)

    monkeypatch.setenv("UV_SCRIPT_MANAGER_CONFIG", str(config_path))
    monkeypatch.setattr("uv_script_manager.cli.verify_uv_available", lambda: True)
    monkeypatch.setattr("uv_script_manager.commands.update.verify_git_available", lambda: None)
    monkeypatch.setattr("uv_script_manager.script_installer.process_script_dependencies", lambda p, d: True)
    monkeypatch.setattr("uv_script_manager.script_installer.verify_script", lambda _: True)

    source_dir = tmp_path / "source"
    source_dir.mkdir()
    script_path = source_dir / "tool.py"
    script_path.write_text("print('version 1')\n", encoding="utf-8")
    helper_file = source_dir / "helper.txt"
    helper_file.write_text("helper v1\n", encoding="utf-8")

    install_result = runner.invoke(cli, ["install", str(source_dir), "--script", "tool.py"])
    assert install_result.exit_code == 0, install_result.output

    state_manager = StateManager(state_file)
    script_info = state_manager.get_script("tool.py")
    assert script_info is not None
    assert script_info.copy_parent_dir is False

    script_path.write_text("print('version 2')\n", encoding="utf-8")
    helper_file.write_text("helper v2\n", encoding="utf-8")

    update_result = runner.invoke(cli, ["update", "tool.py"])
    assert update_result.exit_code == 0, update_result.output

    repo_path = repo_dir / "tool"
    staged_script = repo_path / "tool.py"
    assert staged_script.exists()
    script_content = staged_script.read_text(encoding="utf-8")
    assert "version 2" in script_content

    staged_helper = repo_path / "helper.txt"
    assert not staged_helper.exists(), "helper.txt should not exist in individual script mode"


def test_cli_local_update_with_copy_parent_dir(tmp_path: Path, monkeypatch) -> None:
    """Test updating a local script installed with --copy-parent-dir."""
    runner = CliRunner()

    repo_dir = tmp_path / "repos"
    install_dir = tmp_path / "bin"
    state_file = tmp_path / "state.json"
    config_path = tmp_path / "config.toml"
    _write_config(config_path, repo_dir, install_dir, state_file)

    monkeypatch.setenv("UV_SCRIPT_MANAGER_CONFIG", str(config_path))
    monkeypatch.setattr("uv_script_manager.cli.verify_uv_available", lambda: True)
    monkeypatch.setattr("uv_script_manager.commands.update.verify_git_available", lambda: None)
    monkeypatch.setattr("uv_script_manager.script_installer.process_script_dependencies", lambda p, d: True)
    monkeypatch.setattr("uv_script_manager.script_installer.verify_script", lambda _: True)

    source_dir = tmp_path / "mypackage"
    source_dir.mkdir()
    script_path = source_dir / "cli.py"
    script_path.write_text("print('version 1')\n", encoding="utf-8")
    helper_file = source_dir / "helper.txt"
    helper_file.write_text("helper v1\n", encoding="utf-8")
    subdir = source_dir / "subdir"
    subdir.mkdir()
    (subdir / "data.txt").write_text("data v1\n", encoding="utf-8")

    install_result = runner.invoke(
        cli, ["install", str(source_dir), "--script", "cli.py", "--copy-parent-dir"]
    )
    assert install_result.exit_code == 0, install_result.output

    state_manager = StateManager(state_file)
    script_info = state_manager.get_script("cli.py")
    assert script_info is not None
    assert script_info.copy_parent_dir is True

    repo_path = repo_dir / "mypackage"
    assert (repo_path / "cli.py").exists()
    assert (repo_path / "helper.txt").exists()
    assert (repo_path / "subdir" / "data.txt").exists()

    script_path.write_text("print('version 2')\n", encoding="utf-8")
    helper_file.write_text("helper v2\n", encoding="utf-8")
    (subdir / "data.txt").write_text("data v2\n", encoding="utf-8")
    new_file = source_dir / "newfile.txt"
    new_file.write_text("new content\n", encoding="utf-8")

    update_result = runner.invoke(cli, ["update", "cli.py"])
    assert update_result.exit_code == 0, update_result.output

    staged_script = repo_path / "cli.py"
    assert "version 2" in staged_script.read_text(encoding="utf-8")

    staged_helper = repo_path / "helper.txt"
    assert staged_helper.exists(), "helper.txt should exist in copy-parent-dir mode"
    assert "helper v2" in staged_helper.read_text(encoding="utf-8")

    staged_data = repo_path / "subdir" / "data.txt"
    assert staged_data.exists(), "subdir/data.txt should exist"
    assert "data v2" in staged_data.read_text(encoding="utf-8")

    staged_new = repo_path / "newfile.txt"
    assert staged_new.exists(), "newfile.txt should be copied in update"
    assert "new content" in staged_new.read_text(encoding="utf-8")


@REQUIRES_UV
def test_cli_exact_flag_roundtrip_install_then_update(tmp_path: Path) -> None:
    """Install with --no-exact and update with --exact should toggle shebang."""
    runner = CliRunner()

    repo_dir = tmp_path / "repos"
    install_dir = tmp_path / "bin"
    state_file = tmp_path / "state.json"
    config_path = tmp_path / "config.toml"
    _write_config(config_path, repo_dir, install_dir, state_file)

    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source_script = source_dir / "tool.py"
    source_script.write_text("print('v1')\n", encoding="utf-8")

    install_result = runner.invoke(
        cli,
        [
            "--config",
            str(config_path),
            "install",
            str(source_dir),
            "--script",
            "tool.py",
            "--no-exact",
            "--no-deps",
        ],
    )
    assert install_result.exit_code == 0, install_result.output

    staged_script = repo_dir / "tool" / "tool.py"
    assert staged_script.read_text(encoding="utf-8").splitlines()[0] == "#!/usr/bin/env -S uv run --script"

    source_script.write_text("print('v2')\n", encoding="utf-8")
    update_result = runner.invoke(
        cli,
        ["--config", str(config_path), "update", "tool.py", "--exact"],
    )
    assert update_result.exit_code == 0, update_result.output
    assert staged_script.read_text(encoding="utf-8").splitlines()[0] == (
        "#!/usr/bin/env -S uv run --exact --script"
    )


@REQUIRES_UV
def test_cli_update_refresh_deps_recomputes_local_dependencies(tmp_path: Path) -> None:
    """Local updates with --refresh-deps should recompute dependencies."""
    runner = CliRunner()

    repo_dir = tmp_path / "repos"
    install_dir = tmp_path / "bin"
    state_file = tmp_path / "state.json"
    config_path = tmp_path / "config.toml"
    _write_config(config_path, repo_dir, install_dir, state_file)

    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "tool.py").write_text("print('v1')\n", encoding="utf-8")

    install_result = runner.invoke(
        cli,
        [
            "--config",
            str(config_path),
            "install",
            str(source_dir),
            "--script",
            "tool.py",
            "--no-deps",
        ],
    )
    assert install_result.exit_code == 0, install_result.output

    state_manager = StateManager(state_file)
    script = state_manager.get_script("tool.py")
    assert script is not None
    script.dependencies = ["stale-dependency"]
    state_manager.add_script(script)

    update_result = runner.invoke(
        cli,
        ["--config", str(config_path), "update", "tool.py", "--refresh-deps"],
    )

    assert update_result.exit_code == 0, update_result.output
    assert "Dependencies refreshed:" in update_result.output

    refreshed = StateManager(state_file).get_script("tool.py")
    assert refreshed is not None
    assert refreshed.dependencies == []


@REQUIRES_UV
@REQUIRES_GIT
def test_cli_update_refresh_deps_runs_for_pinned_git_scripts(tmp_path: Path) -> None:
    """Pinned git scripts should still refresh dependencies when requested."""
    runner = CliRunner()

    repo_dir = tmp_path / "repos"
    install_dir = tmp_path / "bin"
    state_file = tmp_path / "state.json"
    config_path = tmp_path / "config.toml"
    _write_config(config_path, repo_dir, install_dir, state_file)

    origin = _create_origin_repo_with_tag(tmp_path)
    state_manager = StateManager(state_file)
    state_manager.add_script(
        ScriptInfo(
            name="tool.py",
            source_type=SourceType.GIT,
            source_url=str(origin),
            ref="v1.0.0",
            ref_type="tag",
            installed_at=datetime.now(),
            repo_path=repo_dir / "tool-repo",
            dependencies=["stale-dependency"],
            commit_hash="00000000",
        )
    )

    result = runner.invoke(
        cli,
        ["--config", str(config_path), "update", "tool.py", "--refresh-deps"],
    )

    assert result.exit_code == 0, result.output
    assert "Pinned (v1.0.0)" not in result.output
    assert "Updated" in result.output

    updated = StateManager(state_file).get_script("tool.py")
    assert updated is not None
    assert updated.ref == "v1.0.0"
    assert updated.ref_type == "tag"
    assert updated.dependencies == []
    assert (updated.repo_path / "tool.py").exists()


def test_cli_update_json_outputs_parseable_payload(tmp_path: Path, monkeypatch) -> None:
    """update --json should emit structured JSON results without table output."""
    runner = CliRunner()

    repo_dir = tmp_path / "repos"
    install_dir = tmp_path / "bin"
    state_file = tmp_path / "state.json"
    config_path = tmp_path / "config.toml"
    _write_config(config_path, repo_dir, install_dir, state_file)

    monkeypatch.setattr("uv_script_manager.cli.verify_uv_available", lambda: True)

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

    single_result = runner.invoke(
        cli,
        ["--config", str(config_path), "update", "tool.py", "--dry-run", "--json"],
    )
    assert single_result.exit_code == 0, single_result.output
    single_payload = json.loads(single_result.output)
    assert single_payload["all"] is False
    assert single_payload["dry_run"] is True
    assert single_payload["results"][0]["status"] == "skipped (local)"

    all_result = runner.invoke(
        cli,
        ["--config", str(config_path), "update", "--all", "--dry-run", "--json"],
    )
    assert all_result.exit_code == 0, all_result.output
    all_payload = json.loads(all_result.output)
    assert all_payload["all"] is True
    assert all_payload["dry_run"] is True
    assert all_payload["results"][0]["status"] == "skipped (local)"


@REQUIRES_UV
@REQUIRES_GIT
def test_cli_update_all_reports_local_and_pinned_statuses(tmp_path: Path) -> None:
    """update --all should report local scripts as skipped and pinned refs as pinned."""
    runner = CliRunner()

    repo_dir = tmp_path / "repos"
    install_dir = tmp_path / "bin"
    state_file = tmp_path / "state.json"
    config_path = tmp_path / "config.toml"
    _write_config(config_path, repo_dir, install_dir, state_file)

    local_repo = repo_dir / "local-repo"
    local_source = tmp_path / "local-source"
    git_repo = repo_dir / "git-repo"
    local_repo.mkdir(parents=True)
    local_source.mkdir(parents=True)
    git_repo.mkdir(parents=True)

    state_manager = StateManager(state_file)
    state_manager.add_script(
        ScriptInfo(
            name="local.py",
            source_type=SourceType.LOCAL,
            installed_at=datetime.now(),
            repo_path=local_repo,
            source_path=local_source,
        )
    )
    state_manager.add_script(
        ScriptInfo(
            name="pinned.py",
            source_type=SourceType.GIT,
            source_url="https://github.com/user/repo",
            ref="v1.0.0",
            ref_type="tag",
            installed_at=datetime.now(),
            repo_path=git_repo,
            commit_hash="deadbeef",
        )
    )

    result = runner.invoke(cli, ["--config", str(config_path), "update", "--all"])

    assert result.exit_code == 0, result.output
    assert "Skipped (local-only)" in result.output
    assert "Pinned (v1.0.0)" in result.output


@REQUIRES_UV
@REQUIRES_GIT
def test_cli_update_reports_up_to_date_status_with_clear_label(tmp_path: Path) -> None:
    """update should label unchanged Git scripts as up-to-date, not as clean state."""
    runner = CliRunner()

    repo_dir = tmp_path / "repos"
    install_dir = tmp_path / "bin"
    state_file = tmp_path / "state.json"
    config_path = tmp_path / "config.toml"
    _write_config(config_path, repo_dir, install_dir, state_file)

    origin = _create_origin_repo_with_tag(tmp_path)
    current_commit = _run_git(origin, "rev-parse", f"--short={GIT_SHORT_HASH_LENGTH}", "main")

    state_manager = StateManager(state_file)
    state_manager.add_script(
        ScriptInfo(
            name="tool.py",
            source_type=SourceType.GIT,
            source_url=str(origin),
            ref="main",
            ref_type="branch",
            installed_at=datetime.now(),
            repo_path=repo_dir / "tool-repo",
            commit_hash=current_commit,
        )
    )

    result = runner.invoke(cli, ["--config", str(config_path), "update", "tool.py"])

    assert result.exit_code == 0, result.output
    assert "Up to date" in result.output


@REQUIRES_UV
@REQUIRES_GIT
def test_cli_update_all_dry_run_reports_would_update_without_mutation(tmp_path: Path) -> None:
    """Dry-run update --all should report updates without modifying state or cloning."""
    runner = CliRunner()

    repo_dir = tmp_path / "repos"
    install_dir = tmp_path / "bin"
    state_file = tmp_path / "state.json"
    config_path = tmp_path / "config.toml"
    _write_config(config_path, repo_dir, install_dir, state_file)

    origin = _create_origin_repo_with_tag(tmp_path)
    (origin / "tool.py").write_text("print('v2')\n", encoding="utf-8")
    _run_git(origin, "add", "tool.py")
    _run_git(
        origin,
        "-c",
        "user.name=Test User",
        "-c",
        "user.email=test@example.com",
        "commit",
        "-m",
        "second",
    )
    old_commit = _run_git(origin, "rev-parse", f"--short={GIT_SHORT_HASH_LENGTH}", "v1.0.0")

    script_repo = repo_dir / "tool-repo"
    state_manager = StateManager(state_file)
    state_manager.add_script(
        ScriptInfo(
            name="tool.py",
            source_type=SourceType.GIT,
            source_url=str(origin),
            ref="main",
            ref_type="branch",
            installed_at=datetime.now(),
            repo_path=script_repo,
            commit_hash=old_commit,
        )
    )

    result = runner.invoke(cli, ["--config", str(config_path), "update", "--all", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "Local" in result.output
    assert "changes" in result.output
    assert "Update available" in result.output
    assert "Unknown" in result.output
    assert not script_repo.exists()

    reloaded = StateManager(state_file).get_script("tool.py")
    assert reloaded is not None
    assert reloaded.commit_hash == old_commit


@REQUIRES_UV
@REQUIRES_GIT
def test_cli_update_all_dry_run_refresh_deps_marks_pinned_as_would_update(tmp_path: Path) -> None:
    """Dry-run update --all with --refresh-deps should report pinned refs as would update."""
    runner = CliRunner()

    repo_dir = tmp_path / "repos"
    install_dir = tmp_path / "bin"
    state_file = tmp_path / "state.json"
    config_path = tmp_path / "config.toml"
    _write_config(config_path, repo_dir, install_dir, state_file)

    origin = _create_origin_repo_with_tag(tmp_path)
    pinned_commit = _run_git(origin, "rev-parse", f"--short={GIT_SHORT_HASH_LENGTH}", "v1.0.0")

    state_manager = StateManager(state_file)
    state_manager.add_script(
        ScriptInfo(
            name="pinned.py",
            source_type=SourceType.GIT,
            source_url=str(origin),
            ref="v1.0.0",
            ref_type="tag",
            installed_at=datetime.now(),
            repo_path=repo_dir / "pinned-repo",
            commit_hash=pinned_commit,
        )
    )

    result = runner.invoke(
        cli,
        ["--config", str(config_path), "update", "--all", "--dry-run", "--refresh-deps"],
    )

    assert result.exit_code == 0, result.output
    assert "Update available" in result.output
    assert "Pinned (v1.0.0)" not in result.output


@REQUIRES_UV
@REQUIRES_GIT
def test_cli_update_all_dry_run_warns_when_local_changes_present(tmp_path: Path) -> None:
    """Dry-run should warn when local repo changes may block an update."""
    runner = CliRunner()

    repo_dir = tmp_path / "repos"
    install_dir = tmp_path / "bin"
    state_file = tmp_path / "state.json"
    config_path = tmp_path / "config.toml"
    _write_config(config_path, repo_dir, install_dir, state_file)

    origin = _create_origin_repo_with_tag(tmp_path)

    script_repo = repo_dir / "tool-repo"
    repo_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", str(origin), str(script_repo)],
        check=True,
        capture_output=True,
        text=True,
    )

    installed_commit = _run_git(script_repo, "rev-parse", f"--short={GIT_SHORT_HASH_LENGTH}", "HEAD")

    (script_repo / "tool.py").write_text("print('local change')\n", encoding="utf-8")

    (origin / "tool.py").write_text("print('remote update')\n", encoding="utf-8")
    _run_git(origin, "add", "tool.py")
    _run_git(
        origin,
        "-c",
        "user.name=Test User",
        "-c",
        "user.email=test@example.com",
        "commit",
        "-m",
        "remote second",
    )

    state_manager = StateManager(state_file)
    state_manager.add_script(
        ScriptInfo(
            name="tool.py",
            source_type=SourceType.GIT,
            source_url=str(origin),
            ref="main",
            ref_type="branch",
            installed_at=datetime.now(),
            repo_path=script_repo,
            commit_hash=installed_commit,
        )
    )

    result = runner.invoke(cli, ["--config", str(config_path), "update", "--all", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "Needs attention" in result.output


@REQUIRES_UV
@REQUIRES_GIT
def test_cli_update_all_dry_run_ignores_uv_managed_script_changes(tmp_path: Path) -> None:
    """Dry-run should not flag uv-managed shebang/metadata changes as custom."""
    runner = CliRunner()

    repo_dir = tmp_path / "repos"
    install_dir = tmp_path / "bin"
    state_file = tmp_path / "state.json"
    config_path = tmp_path / "config.toml"
    _write_config(config_path, repo_dir, install_dir, state_file)

    origin = _create_origin_repo_with_tag(tmp_path)

    script_repo = repo_dir / "tool-repo"
    repo_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", str(origin), str(script_repo)],
        check=True,
        capture_output=True,
        text=True,
    )
    installed_commit = _run_git(script_repo, "rev-parse", f"--short={GIT_SHORT_HASH_LENGTH}", "HEAD")

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

    (origin / "tool.py").write_text("print('v2')\n", encoding="utf-8")
    _run_git(origin, "add", "tool.py")
    _run_git(
        origin,
        "-c",
        "user.name=Test User",
        "-c",
        "user.email=test@example.com",
        "commit",
        "-m",
        "remote second",
    )

    state_manager = StateManager(state_file)
    state_manager.add_script(
        ScriptInfo(
            name="tool.py",
            source_type=SourceType.GIT,
            source_url=str(origin),
            ref="main",
            ref_type="branch",
            installed_at=datetime.now(),
            repo_path=script_repo,
            commit_hash=installed_commit,
        )
    )

    result = runner.invoke(cli, ["--config", str(config_path), "update", "--all", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "Update available" in result.output
    assert "local custom changes present" not in result.output
    assert "Managed" in result.output


@REQUIRES_UV
@REQUIRES_GIT
def test_cli_update_clears_managed_changes_and_reapplies_shebang(tmp_path: Path) -> None:
    """Update should clear uv-managed local changes and reapply shebang after pull."""
    runner = CliRunner()

    repo_dir = tmp_path / "repos"
    install_dir = tmp_path / "bin"
    state_file = tmp_path / "state.json"
    config_path = tmp_path / "config.toml"
    _write_config(config_path, repo_dir, install_dir, state_file)

    origin = _create_origin_repo_with_tag(tmp_path)

    script_repo = repo_dir / "tool-repo"
    repo_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", str(origin), str(script_repo)],
        check=True,
        capture_output=True,
        text=True,
    )
    installed_commit = _run_git(script_repo, "rev-parse", f"--short={GIT_SHORT_HASH_LENGTH}", "HEAD")

    (script_repo / "tool.py").write_text(
        "#!/usr/bin/env -S uv run --exact --script\nprint('v1')\n",
        encoding="utf-8",
    )

    (origin / "tool.py").write_text("print('v2')\n", encoding="utf-8")
    _run_git(origin, "add", "tool.py")
    _run_git(
        origin,
        "-c",
        "user.name=Test User",
        "-c",
        "user.email=test@example.com",
        "commit",
        "-m",
        "remote second",
    )

    state_manager = StateManager(state_file)
    state_manager.add_script(
        ScriptInfo(
            name="tool.py",
            source_type=SourceType.GIT,
            source_url=str(origin),
            ref="main",
            ref_type="branch",
            installed_at=datetime.now(),
            repo_path=script_repo,
            commit_hash=installed_commit,
        )
    )

    result = runner.invoke(cli, ["--config", str(config_path), "update", "tool.py"])

    assert result.exit_code == 0, result.output
    assert "Updated" in result.output

    updated_content = (script_repo / "tool.py").read_text(encoding="utf-8")
    assert updated_content.splitlines()[0] == "#!/usr/bin/env -S uv run --exact --script"
    assert "v2" in updated_content
