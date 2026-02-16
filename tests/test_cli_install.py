"""CLI install command integration tests."""

from pathlib import Path

from click.testing import CliRunner

from tests.cli_helpers import REQUIRES_UV, _write_config
from uv_helper.cli import cli
from uv_helper.constants import SourceType
from uv_helper.state import StateManager


def test_cli_local_install_update_and_remove(tmp_path: Path, monkeypatch) -> None:
    """End-to-end check for local installs without requiring git."""
    runner = CliRunner()

    repo_dir = tmp_path / "repos"
    install_dir = tmp_path / "bin"
    state_file = tmp_path / "state.json"
    config_path = tmp_path / "config.toml"
    _write_config(config_path, repo_dir, install_dir, state_file)

    monkeypatch.setenv("UV_HELPER_CONFIG", str(config_path))
    monkeypatch.setattr("uv_helper.cli.verify_uv_available", lambda: True)

    def _fail_if_git_called() -> None:
        raise AssertionError("git verification should not run")

    monkeypatch.setattr("uv_helper.commands.install.verify_git_available", _fail_if_git_called)

    dependencies_seen: dict[str, list[str]] = {}

    def fake_process_dependencies(path: Path, deps: list[str]) -> bool:
        dependencies_seen["value"] = deps.copy()
        assert path.name == "tool.py"
        return True

    monkeypatch.setattr(
        "uv_helper.script_installer.process_script_dependencies",
        fake_process_dependencies,
    )
    monkeypatch.setattr("uv_helper.script_installer.verify_script", lambda _: True)

    source_dir = tmp_path / "source"
    (source_dir / "pkg").mkdir(parents=True)
    script_rel = "pkg/tool.py"
    (source_dir / script_rel).write_text("print('hi')\n", encoding="utf-8")
    (source_dir / "requirements.txt").write_text("requests\n", encoding="utf-8")

    install_result = runner.invoke(cli, ["install", str(source_dir), "--script", script_rel])
    assert install_result.exit_code == 0, install_result.output

    assert dependencies_seen["value"] == ["requests"]

    repo_path = repo_dir / "pkg-tool"
    staged_script = repo_path / script_rel
    assert staged_script.exists()
    assert staged_script.read_text(encoding="utf-8").splitlines()[0] == (
        "#!/usr/bin/env -S uv run --exact --script"
    )

    symlink_path = install_dir / "tool.py"
    assert symlink_path.exists()
    assert symlink_path.is_symlink()
    assert symlink_path.resolve() == staged_script

    state_manager = StateManager(state_file)
    script_info = state_manager.get_script(script_rel)
    assert script_info is not None
    assert script_info.source_type == SourceType.LOCAL
    assert script_info.source_path == source_dir
    assert script_info.dependencies == ["requests"]

    update_all_result = runner.invoke(cli, ["update", "--all"])
    assert update_all_result.exit_code == 0, update_all_result.output
    assert "Skipped (local-only)" in update_all_result.output

    remove_result = runner.invoke(cli, ["remove", script_rel], input="y\n")
    assert remove_result.exit_code == 0, remove_result.output
    assert str(source_dir) in remove_result.output
    assert not symlink_path.exists()
    assert state_manager.get_script(script_rel) is None


def test_cli_install_with_add_source_package(tmp_path: Path, monkeypatch) -> None:
    """Test install with --add-source-package flag."""
    runner = CliRunner()

    repo_dir = tmp_path / "repos"
    install_dir = tmp_path / "bin"
    state_file = tmp_path / "state.json"
    config_path = tmp_path / "config.toml"
    _write_config(config_path, repo_dir, install_dir, state_file)

    monkeypatch.setenv("UV_HELPER_CONFIG", str(config_path))
    monkeypatch.setattr("uv_helper.cli.verify_uv_available", lambda: True)
    monkeypatch.setattr("uv_helper.commands.install.verify_git_available", lambda: None)

    dependencies_seen: dict[str, list[str]] = {}

    def fake_process_dependencies(path: Path, deps: list[str]) -> bool:
        dependencies_seen["value"] = deps.copy()
        return True

    monkeypatch.setattr(
        "uv_helper.script_installer.process_script_dependencies",
        fake_process_dependencies,
    )
    monkeypatch.setattr("uv_helper.script_installer.verify_script", lambda _: True)

    source_dir = tmp_path / "mypackage"
    source_dir.mkdir()
    (source_dir / "__init__.py").write_text("# package init\n", encoding="utf-8")
    script_path = source_dir / "cli.py"
    script_path.write_text("print('hello from cli')\n", encoding="utf-8")

    install_result = runner.invoke(
        cli,
        [
            "install",
            str(source_dir),
            "--script",
            "cli.py",
            "--copy-parent-dir",
            "--add-source-package",
            "mypackage",
        ],
    )
    assert install_result.exit_code == 0, install_result.output

    assert "mypackage" in dependencies_seen["value"]

    staged_script = repo_dir / "mypackage" / "cli.py"
    assert staged_script.exists()
    content = staged_script.read_text(encoding="utf-8")
    assert "# [tool.uv.sources]" in content
    assert "# mypackage = { path = " in content

    state_manager = StateManager(state_file)
    script_info = state_manager.get_script("cli.py")
    assert script_info is not None
    assert "mypackage" in script_info.dependencies


def test_cli_install_requires_script_flag() -> None:
    """Install without --script should fail in non-interactive mode."""
    runner = CliRunner()
    result = runner.invoke(cli, ["install", "https://github.com/user/repo"])
    assert result.exit_code != 0
    assert "--script is required in non-interactive mode" in result.output


def test_cli_install_prompts_for_script_when_interactive(tmp_path: Path, monkeypatch) -> None:
    """Install should prompt for script selection when --script is omitted in TTY mode."""
    runner = CliRunner()

    repo_dir = tmp_path / "repos"
    install_dir = tmp_path / "bin"
    state_file = tmp_path / "state.json"
    config_path = tmp_path / "config.toml"
    _write_config(config_path, repo_dir, install_dir, state_file)

    monkeypatch.setattr("uv_helper.cli.verify_uv_available", lambda: True)

    monkeypatch.setattr("uv_helper.cli._is_interactive_terminal", lambda: True)
    monkeypatch.setattr(
        "uv_helper.cli._discover_install_script_candidates",
        lambda source, clone_depth: ["a.py", "pkg/b.py"],
    )

    captured: dict[str, tuple[str, ...]] = {}

    def fake_install(self, source: str, scripts: tuple[str, ...], request):
        captured["scripts"] = scripts
        return [(scripts[0], True, install_dir / scripts[0])]

    monkeypatch.setattr("uv_helper.cli.InstallHandler.install", fake_install)

    result = runner.invoke(
        cli,
        ["--config", str(config_path), "install", "https://github.com/user/repo"],
        input="2\n",
    )

    assert result.exit_code == 0, result.output
    assert captured["scripts"] == ("pkg/b.py",)


def test_cli_install_invalid_source(tmp_path: Path, monkeypatch) -> None:
    """Test that install fails with invalid source."""
    runner = CliRunner()

    config_path = tmp_path / "config.toml"
    _write_config(config_path, tmp_path / "repos", tmp_path / "bin", tmp_path / "state.json")

    monkeypatch.setenv("UV_HELPER_CONFIG", str(config_path))
    monkeypatch.setattr("uv_helper.cli.verify_uv_available", lambda: True)

    result = runner.invoke(cli, ["install", "not-a-url-or-path", "--script", "tool.py"])

    assert result.exit_code != 0
    assert "Invalid source" in result.output


def test_cli_install_script_not_found(tmp_path: Path, monkeypatch) -> None:
    """Test that install fails if script doesn't exist in source."""
    runner = CliRunner()

    repo_dir = tmp_path / "repos"
    install_dir = tmp_path / "bin"
    state_file = tmp_path / "state.json"
    config_path = tmp_path / "config.toml"
    _write_config(config_path, repo_dir, install_dir, state_file)

    monkeypatch.setenv("UV_HELPER_CONFIG", str(config_path))
    monkeypatch.setattr("uv_helper.cli.verify_uv_available", lambda: True)
    monkeypatch.setattr("uv_helper.commands.install.verify_git_available", lambda: None)

    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "other.py").write_text("print('other')\n", encoding="utf-8")

    result = runner.invoke(cli, ["install", str(source_dir), "--script", "missing.py"])

    assert result.exit_code != 0
    assert "missing.py" in result.output
    assert "Not found" in result.output or "not found" in result.output


def test_cli_install_add_source_without_copy_parent(tmp_path: Path, monkeypatch) -> None:
    """Test that --add-source-package requires --copy-parent-dir for local sources."""
    runner = CliRunner()

    config_path = tmp_path / "config.toml"
    _write_config(config_path, tmp_path / "repos", tmp_path / "bin", tmp_path / "state.json")

    monkeypatch.setenv("UV_HELPER_CONFIG", str(config_path))
    monkeypatch.setattr("uv_helper.cli.verify_uv_available", lambda: True)

    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "script.py").write_text("print('test')\n", encoding="utf-8")

    result = runner.invoke(
        cli,
        [
            "install",
            str(source_dir),
            "--script",
            "script.py",
            "--add-source-package",
            "mypkg",
        ],
    )

    assert result.exit_code != 0
    assert "--add-source-package requires --copy-parent-dir" in result.output


def test_cli_install_interactive_discovery_failure_exits(tmp_path: Path, monkeypatch) -> None:
    """install should exit with guidance when interactive discovery fails."""
    runner = CliRunner()
    repo_dir = tmp_path / "repos"
    install_dir = tmp_path / "bin"
    state_file = tmp_path / "state.json"
    config_path = tmp_path / "config.toml"
    _write_config(config_path, repo_dir, install_dir, state_file)

    source_dir = tmp_path / "source"
    source_dir.mkdir()

    monkeypatch.setattr("uv_helper.cli.verify_uv_available", lambda: True)
    monkeypatch.setattr("uv_helper.cli._is_interactive_terminal", lambda: True)
    monkeypatch.setattr(
        "uv_helper.cli._discover_install_script_candidates",
        lambda source, clone_depth: (_ for _ in ()).throw(ValueError("clone failed")),
    )

    result = runner.invoke(
        cli,
        ["--config", str(config_path), "install", str(source_dir)],
    )

    assert result.exit_code != 0
    assert "Failed to discover scripts" in result.output


def test_cli_install_interactive_no_candidates_exits(tmp_path: Path, monkeypatch) -> None:
    """install should exit with browse hint when discovery returns no scripts."""
    runner = CliRunner()
    repo_dir = tmp_path / "repos"
    install_dir = tmp_path / "bin"
    state_file = tmp_path / "state.json"
    config_path = tmp_path / "config.toml"
    _write_config(config_path, repo_dir, install_dir, state_file)

    source_dir = tmp_path / "source"
    source_dir.mkdir()

    monkeypatch.setattr("uv_helper.cli.verify_uv_available", lambda: True)
    monkeypatch.setattr("uv_helper.cli._is_interactive_terminal", lambda: True)
    monkeypatch.setattr("uv_helper.cli._discover_install_script_candidates", lambda *_args: [])

    result = runner.invoke(
        cli,
        ["--config", str(config_path), "install", str(source_dir)],
    )

    assert result.exit_code != 0
    assert "No installable Python scripts found" in result.output
    assert "browse <source> --all" in result.output


def test_cli_install_rejects_alias_with_multiple_scripts(tmp_path: Path, monkeypatch) -> None:
    """install should reject --alias when multiple scripts are provided."""
    runner = CliRunner()
    repo_dir = tmp_path / "repos"
    install_dir = tmp_path / "bin"
    state_file = tmp_path / "state.json"
    config_path = tmp_path / "config.toml"
    _write_config(config_path, repo_dir, install_dir, state_file)

    monkeypatch.setattr("uv_helper.cli.verify_uv_available", lambda: True)

    result = runner.invoke(
        cli,
        [
            "--config",
            str(config_path),
            "install",
            "https://github.com/acme/repo",
            "--script",
            "a.py",
            "--script",
            "b.py",
            "--alias",
            "short",
        ],
    )

    assert result.exit_code != 0
    assert "--alias can only be used when installing a single script" in result.output


def test_cli_install_prints_multi_script_next_hint(tmp_path: Path, monkeypatch) -> None:
    """install should show list hint after multiple successful installs."""
    runner = CliRunner()
    repo_dir = tmp_path / "repos"
    install_dir = tmp_path / "bin"
    state_file = tmp_path / "state.json"
    config_path = tmp_path / "config.toml"
    _write_config(config_path, repo_dir, install_dir, state_file)

    monkeypatch.setattr("uv_helper.cli.verify_uv_available", lambda: True)
    monkeypatch.setattr(
        "uv_helper.cli.InstallHandler.install",
        lambda self, source, scripts, request: [
            ("a.py", True, install_dir / "a.py"),
            ("b.py", True, install_dir / "b.py"),
        ],
    )

    result = runner.invoke(
        cli,
        [
            "--config",
            str(config_path),
            "install",
            "https://github.com/acme/repo",
            "--script",
            "a.py",
            "--script",
            "b.py",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Next: uv-helper list --verbose" in result.output


def test_cli_install_reports_no_symlink_location_consistently(tmp_path: Path, monkeypatch) -> None:
    """install should show a clear location label when symlink creation is disabled."""
    runner = CliRunner()
    repo_dir = tmp_path / "repos"
    install_dir = tmp_path / "bin"
    state_file = tmp_path / "state.json"
    config_path = tmp_path / "config.toml"
    _write_config(config_path, repo_dir, install_dir, state_file)

    source_dir = tmp_path / "source"
    source_dir.mkdir()

    monkeypatch.setattr("uv_helper.cli.verify_uv_available", lambda: True)
    monkeypatch.setattr(
        "uv_helper.cli.InstallHandler.install",
        lambda self, source, scripts, request: [("tool.py", True, None)],
    )

    result = runner.invoke(
        cli,
        [
            "--config",
            str(config_path),
            "install",
            str(source_dir),
            "--script",
            "tool.py",
            "--no-symlink",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Not symlinked" in result.output


@REQUIRES_UV
def test_cli_alias_lifecycle_install_show_update_remove(tmp_path: Path) -> None:
    """Alias should work consistently across install, show, update, and remove."""
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
            "--alias",
            "short",
            "--no-deps",
        ],
    )
    assert install_result.exit_code == 0, install_result.output

    alias_symlink = install_dir / "short"
    assert alias_symlink.exists()
    assert alias_symlink.is_symlink()

    show_result = runner.invoke(cli, ["--config", str(config_path), "show", "short"])
    assert show_result.exit_code == 0, show_result.output
    assert "Alias:" in show_result.output
    assert "short" in show_result.output

    source_script.write_text("print('v2')\n", encoding="utf-8")
    update_result = runner.invoke(cli, ["--config", str(config_path), "update", "short"])
    assert update_result.exit_code == 0, update_result.output

    staged_script = repo_dir / "tool" / "tool.py"
    assert "v2" in staged_script.read_text(encoding="utf-8")

    remove_result = runner.invoke(cli, ["--config", str(config_path), "remove", "short", "--force"])
    assert remove_result.exit_code == 0, remove_result.output
    assert not alias_symlink.exists()

    state_manager = StateManager(state_file)
    assert state_manager.get_script("tool.py") is None


@REQUIRES_UV
def test_cli_install_force_reinstall_is_idempotent(tmp_path: Path) -> None:
    """Repeated force installs should keep a single state entry for the script."""
    runner = CliRunner()

    repo_dir = tmp_path / "repos"
    install_dir = tmp_path / "bin"
    state_file = tmp_path / "state.json"
    config_path = tmp_path / "config.toml"
    _write_config(config_path, repo_dir, install_dir, state_file)

    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "tool.py").write_text("print('hello')\n", encoding="utf-8")

    first_install = runner.invoke(
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
    assert first_install.exit_code == 0, first_install.output

    second_install = runner.invoke(
        cli,
        [
            "--config",
            str(config_path),
            "install",
            str(source_dir),
            "--script",
            "tool.py",
            "--no-deps",
            "--force",
        ],
    )
    assert second_install.exit_code == 0, second_install.output

    scripts = StateManager(state_file).list_scripts()
    assert len(scripts) == 1
    assert scripts[0].name == "tool.py"
    assert (install_dir / "tool.py").is_symlink()
