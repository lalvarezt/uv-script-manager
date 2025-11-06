"""CLI integration tests for UV-Helper."""

from pathlib import Path

from click.testing import CliRunner

from uv_helper.cli import cli
from uv_helper.constants import SourceType
from uv_helper.state import StateManager


def _write_config(config_path: Path, repo_dir: Path, install_dir: Path, state_file: Path) -> None:
    config_path.write_text(
        "\n".join(
            [
                "[paths]",
                f'repo_dir = "{repo_dir}"',
                f'install_dir = "{install_dir}"',
                f'state_file = "{state_file}"',
                "",
                "[git]",
                "clone_depth = 1",
                "",
                "[install]",
                "auto_symlink = true",
                "verify_after_install = true",
                "auto_chmod = true",
                "use_exact_flag = true",
            ]
        ),
        encoding="utf-8",
    )


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

    monkeypatch.setattr("uv_helper.cli.verify_git_available", _fail_if_git_called)

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

    update_all_result = runner.invoke(cli, ["update-all"])
    assert update_all_result.exit_code == 0, update_all_result.output
    assert "skipped (local)" in update_all_result.output

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
    monkeypatch.setattr("uv_helper.cli.verify_git_available", lambda: None)

    dependencies_seen: dict[str, list[str]] = {}

    def fake_process_dependencies(path: Path, deps: list[str]) -> bool:
        dependencies_seen["value"] = deps.copy()
        return True

    monkeypatch.setattr(
        "uv_helper.script_installer.process_script_dependencies",
        fake_process_dependencies,
    )
    monkeypatch.setattr("uv_helper.script_installer.verify_script", lambda _: True)

    # Create source directory with package structure
    source_dir = tmp_path / "mypackage"
    source_dir.mkdir()
    (source_dir / "__init__.py").write_text("# package init\n", encoding="utf-8")
    script_path = source_dir / "cli.py"
    script_path.write_text("print('hello from cli')\n", encoding="utf-8")

    # Install with --copy-parent-dir and --add-source-package
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

    # Verify dependencies include the package
    assert "mypackage" in dependencies_seen["value"]

    # Verify the script has [tool.uv.sources] metadata
    staged_script = repo_dir / "mypackage" / "cli.py"
    assert staged_script.exists()
    content = staged_script.read_text(encoding="utf-8")
    assert "# [tool.uv.sources]" in content
    assert "# mypackage = { path = " in content

    # Verify state includes the package in dependencies
    state_manager = StateManager(state_file)
    script_info = state_manager.get_script("cli.py")
    assert script_info is not None
    assert "mypackage" in script_info.dependencies


def test_cli_install_requires_script_flag() -> None:
    """Test that install command requires --script flag."""
    runner = CliRunner()
    result = runner.invoke(cli, ["install", "https://github.com/user/repo"])
    assert result.exit_code != 0


def test_cli_install_invalid_source(tmp_path: Path, monkeypatch) -> None:
    """Test that install fails with invalid source."""
    runner = CliRunner()

    config_path = tmp_path / "config.toml"
    _write_config(config_path, tmp_path / "repos", tmp_path / "bin", tmp_path / "state.json")

    monkeypatch.setenv("UV_HELPER_CONFIG", str(config_path))
    monkeypatch.setattr("uv_helper.cli.verify_uv_available", lambda: True)

    # Neither a valid Git URL nor an existing directory
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
    monkeypatch.setattr("uv_helper.cli.verify_git_available", lambda: None)

    # Create source directory without the requested script
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "other.py").write_text("print('other')\n", encoding="utf-8")

    result = runner.invoke(cli, ["install", str(source_dir), "--script", "missing.py"])

    assert result.exit_code == 0  # CLI doesn't fail, but reports error in table
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


def test_cli_remove_nonexistent_script(tmp_path: Path, monkeypatch) -> None:
    """Test that remove fails for nonexistent script."""
    runner = CliRunner()

    config_path = tmp_path / "config.toml"
    _write_config(config_path, tmp_path / "repos", tmp_path / "bin", tmp_path / "state.json")

    monkeypatch.setenv("UV_HELPER_CONFIG", str(config_path))
    monkeypatch.setattr("uv_helper.cli.verify_uv_available", lambda: True)

    result = runner.invoke(cli, ["remove", "nonexistent.py"])

    assert result.exit_code != 0
    assert "not found" in result.output.lower()


def test_cli_update_nonexistent_script(tmp_path: Path, monkeypatch) -> None:
    """Test that update fails for nonexistent script."""
    runner = CliRunner()

    config_path = tmp_path / "config.toml"
    _write_config(config_path, tmp_path / "repos", tmp_path / "bin", tmp_path / "state.json")

    monkeypatch.setenv("UV_HELPER_CONFIG", str(config_path))
    monkeypatch.setattr("uv_helper.cli.verify_uv_available", lambda: True)

    result = runner.invoke(cli, ["update", "nonexistent.py"])

    assert result.exit_code != 0
    assert "not found" in result.output.lower()


def test_cli_local_update_without_copy_parent_dir(tmp_path: Path, monkeypatch) -> None:
    """Test updating a local script installed without --copy-parent-dir."""
    runner = CliRunner()

    repo_dir = tmp_path / "repos"
    install_dir = tmp_path / "bin"
    state_file = tmp_path / "state.json"
    config_path = tmp_path / "config.toml"
    _write_config(config_path, repo_dir, install_dir, state_file)

    monkeypatch.setenv("UV_HELPER_CONFIG", str(config_path))
    monkeypatch.setattr("uv_helper.cli.verify_uv_available", lambda: True)
    monkeypatch.setattr("uv_helper.cli.verify_git_available", lambda: None)
    monkeypatch.setattr("uv_helper.script_installer.process_script_dependencies", lambda p, d: True)
    monkeypatch.setattr("uv_helper.script_installer.verify_script", lambda _: True)

    # Create source directory with a script
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    script_path = source_dir / "tool.py"
    script_path.write_text("print('version 1')\n", encoding="utf-8")
    helper_file = source_dir / "helper.txt"
    helper_file.write_text("helper v1\n", encoding="utf-8")

    # Install without --copy-parent-dir (individual script mode)
    install_result = runner.invoke(cli, ["install", str(source_dir), "--script", "tool.py"])
    assert install_result.exit_code == 0, install_result.output

    # Verify copy_parent_dir is False
    state_manager = StateManager(state_file)
    script_info = state_manager.get_script("tool.py")
    assert script_info is not None
    assert script_info.copy_parent_dir is False

    # Modify the script in source
    script_path.write_text("print('version 2')\n", encoding="utf-8")
    helper_file.write_text("helper v2\n", encoding="utf-8")

    # Update the script
    update_result = runner.invoke(cli, ["update", "tool.py"])
    assert update_result.exit_code == 0, update_result.output

    # Verify only the script was updated, not helper.txt
    repo_path = repo_dir / "tool"
    staged_script = repo_path / "tool.py"
    assert staged_script.exists()
    script_content = staged_script.read_text(encoding="utf-8")
    assert "version 2" in script_content

    # Helper file should not be copied in individual script mode
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

    monkeypatch.setenv("UV_HELPER_CONFIG", str(config_path))
    monkeypatch.setattr("uv_helper.cli.verify_uv_available", lambda: True)
    monkeypatch.setattr("uv_helper.cli.verify_git_available", lambda: None)
    monkeypatch.setattr("uv_helper.script_installer.process_script_dependencies", lambda p, d: True)
    monkeypatch.setattr("uv_helper.script_installer.verify_script", lambda _: True)

    # Create source directory with a script and additional files
    source_dir = tmp_path / "mypackage"
    source_dir.mkdir()
    script_path = source_dir / "cli.py"
    script_path.write_text("print('version 1')\n", encoding="utf-8")
    helper_file = source_dir / "helper.txt"
    helper_file.write_text("helper v1\n", encoding="utf-8")
    subdir = source_dir / "subdir"
    subdir.mkdir()
    (subdir / "data.txt").write_text("data v1\n", encoding="utf-8")

    # Install with --copy-parent-dir (entire directory mode)
    install_result = runner.invoke(
        cli, ["install", str(source_dir), "--script", "cli.py", "--copy-parent-dir"]
    )
    assert install_result.exit_code == 0, install_result.output

    # Verify copy_parent_dir is True
    state_manager = StateManager(state_file)
    script_info = state_manager.get_script("cli.py")
    assert script_info is not None
    assert script_info.copy_parent_dir is True

    # Verify entire directory was copied initially
    repo_path = repo_dir / "mypackage"
    assert (repo_path / "cli.py").exists()
    assert (repo_path / "helper.txt").exists()
    assert (repo_path / "subdir" / "data.txt").exists()

    # Modify files in source
    script_path.write_text("print('version 2')\n", encoding="utf-8")
    helper_file.write_text("helper v2\n", encoding="utf-8")
    (subdir / "data.txt").write_text("data v2\n", encoding="utf-8")
    new_file = source_dir / "newfile.txt"
    new_file.write_text("new content\n", encoding="utf-8")

    # Update the script
    update_result = runner.invoke(cli, ["update", "cli.py"])
    assert update_result.exit_code == 0, update_result.output

    # Verify entire directory was refreshed, including all files
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
