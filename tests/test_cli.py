"""CLI integration tests for UV-Helper."""

import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import pytest
from click.testing import CliRunner

from uv_helper.cli import cli
from uv_helper.constants import GIT_SHORT_HASH_LENGTH, SourceType
from uv_helper.state import ScriptInfo, StateManager

REQUIRES_UV = pytest.mark.skipif(shutil.which("uv") is None, reason="uv command required")
REQUIRES_GIT = pytest.mark.skipif(shutil.which("git") is None, reason="git command required")
REQUIRES_UV_HELPER = pytest.mark.skipif(
    shutil.which("uv-helper") is None,
    reason="uv-helper executable required",
)


def _run_git(repo_path: Path, *args: str) -> str:
    """Run a git command in the given repository and return stdout."""
    result = subprocess.run(
        ["git", *args],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _create_origin_repo_with_tag(tmp_path: Path) -> Path:
    """Create a local git origin with a tagged script commit."""
    origin = tmp_path / "origin"
    origin.mkdir()

    _run_git(origin, "init", "-b", "main")
    (origin / "tool.py").write_text("print('v1')\n", encoding="utf-8")
    _run_git(origin, "add", "tool.py")
    _run_git(
        origin,
        "-c",
        "user.name=Test User",
        "-c",
        "user.email=test@example.com",
        "commit",
        "-m",
        "initial",
    )
    _run_git(origin, "tag", "v1.0.0")
    return origin


def _write_config(
    config_path: Path,
    repo_dir: Path,
    install_dir: Path,
    state_file: Path,
    list_verbose_fallback: bool | None = None,
    list_min_width: int | None = None,
) -> None:
    lines = [
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

    if list_verbose_fallback is not None or list_min_width is not None:
        lines.extend(
            [
                "",
                "[commands.list]",
            ]
        )
        if list_verbose_fallback is not None:
            value = "true" if list_verbose_fallback else "false"
            lines.append(f"verbose_fallback = {value}")
        if list_min_width is not None:
            lines.append(f"min_width = {list_min_width}")

    config_path.write_text(
        "\n".join(lines),
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
    monkeypatch.setattr("uv_helper.commands.install.verify_git_available", lambda: None)

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
    monkeypatch.setattr("uv_helper.commands.update.verify_git_available", lambda: None)
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
    monkeypatch.setattr("uv_helper.commands.update.verify_git_available", lambda: None)
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


@REQUIRES_UV
def test_cli_import_dry_run_uses_ref_type_for_rendering(tmp_path: Path) -> None:
    """Dry-run import should render branch refs with # and pinned refs with @."""
    runner = CliRunner()

    repo_dir = tmp_path / "repos"
    install_dir = tmp_path / "bin"
    state_file = tmp_path / "state.json"
    config_path = tmp_path / "config.toml"
    _write_config(config_path, repo_dir, install_dir, state_file)

    import_file = tmp_path / "import.json"
    import_file.write_text(
        json.dumps(
            {
                "version": 1,
                "scripts": [
                    {
                        "name": "branch-tool.py",
                        "source_type": "git",
                        "source": "https://github.com/user/repo",
                        "ref": "main",
                        "ref_type": "branch",
                    },
                    {
                        "name": "tag-tool.py",
                        "source_type": "git",
                        "source": "https://github.com/user/repo",
                        "ref": "v1.2.3",
                        "ref_type": "tag",
                    },
                    {
                        "name": "commit-tool.py",
                        "source_type": "git",
                        "source": "https://github.com/user/repo",
                        "ref": "deadbeef",
                        "ref_type": "commit",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        cli,
        ["--config", str(config_path), "import", str(import_file), "--dry-run"],
    )

    assert result.exit_code == 0, result.output
    assert "branch-tool.py" in result.output
    assert "#main" in result.output
    assert "tag-tool.py" in result.output
    assert "@v1.2.3" in result.output
    assert "commit-tool.py" in result.output
    assert "@deadbeef" in result.output


@REQUIRES_UV
def test_cli_import_dry_run_legacy_commit_like_ref_uses_at(tmp_path: Path) -> None:
    """Dry-run import should treat legacy commit-like refs as pinned (@ref)."""
    runner = CliRunner()

    repo_dir = tmp_path / "repos"
    install_dir = tmp_path / "bin"
    state_file = tmp_path / "state.json"
    config_path = tmp_path / "config.toml"
    _write_config(config_path, repo_dir, install_dir, state_file)

    import_file = tmp_path / "import-legacy.json"
    import_file.write_text(
        json.dumps(
            {
                "version": 1,
                "scripts": [
                    {
                        "name": "legacy-commit.py",
                        "source_type": "git",
                        "source": "https://github.com/user/repo",
                        "ref": "deadbeef",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        cli,
        ["--config", str(config_path), "import", str(import_file), "--dry-run"],
    )

    assert result.exit_code == 0, result.output
    assert "legacy-commit.py" in result.output
    assert "@deadbeef" in result.output


@REQUIRES_UV
@REQUIRES_GIT
def test_cli_update_all_reports_local_and_pinned_statuses(tmp_path: Path) -> None:
    """update-all should report local scripts as skipped and pinned refs as pinned."""
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

    result = runner.invoke(cli, ["--config", str(config_path), "update-all"])

    assert result.exit_code == 0, result.output
    assert "skipped (local)" in result.output
    assert "pinned to v1.0.0" in result.output


@REQUIRES_UV
@REQUIRES_GIT
def test_cli_update_all_dry_run_reports_would_update_without_mutation(tmp_path: Path) -> None:
    """Dry-run update-all should report updates without modifying state or cloning."""
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

    result = runner.invoke(cli, ["--config", str(config_path), "update-all", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "Local" in result.output
    assert "changes" in result.output
    assert "would update" in result.output
    assert "Unknown" in result.output
    assert not script_repo.exists()

    reloaded = StateManager(state_file).get_script("tool.py")
    assert reloaded is not None
    assert reloaded.commit_hash == old_commit


@REQUIRES_UV
@REQUIRES_GIT
def test_cli_update_all_dry_run_refresh_deps_marks_pinned_as_would_update(tmp_path: Path) -> None:
    """Dry-run with --refresh-deps should report pinned refs as would update."""
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
        ["--config", str(config_path), "update-all", "--dry-run", "--refresh-deps"],
    )

    assert result.exit_code == 0, result.output
    assert "would update" in result.output
    assert "pinned to v1.0.0" not in result.output


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

    # Leave local uncommitted changes in the tracked script.
    (script_repo / "tool.py").write_text("print('local change')\n", encoding="utf-8")

    # Add a conflicting remote update so a real pull can be blocked.
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

    result = runner.invoke(cli, ["--config", str(config_path), "update-all", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "would update (local custom changes present)" in result.output
    assert "Yes" in result.output


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

    # Emulate uv-managed script transformations.
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

    # Add a remote update.
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

    result = runner.invoke(cli, ["--config", str(config_path), "update-all", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "would update" in result.output
    assert "local custom changes present" not in result.output
    assert "No" in result.output
    assert "(managed)" in result.output


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

    # Emulate a prior uv-managed shebang modification in the working tree.
    (script_repo / "tool.py").write_text(
        "#!/usr/bin/env -S uv run --exact --script\nprint('v1')\n",
        encoding="utf-8",
    )

    # Add a remote update.
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


@REQUIRES_UV
def test_cli_export_import_roundtrip_local_install_no_deps(tmp_path: Path) -> None:
    """Exported local installs should import cleanly with no extra mocking."""
    runner = CliRunner()

    repo_dir = tmp_path / "repos"
    install_dir = tmp_path / "bin"
    state_file = tmp_path / "state.json"
    config_path = tmp_path / "config.toml"
    _write_config(config_path, repo_dir, install_dir, state_file)

    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "tool.py").write_text("print('hello')\n", encoding="utf-8")

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

    export_file = tmp_path / "scripts.json"
    export_result = runner.invoke(
        cli,
        ["--config", str(config_path), "export", "-o", str(export_file)],
    )
    assert export_result.exit_code == 0, export_result.output
    assert export_file.exists()

    exported = json.loads(export_file.read_text(encoding="utf-8"))
    assert exported["scripts"][0]["source_type"] == "local"

    remove_result = runner.invoke(
        cli,
        ["--config", str(config_path), "remove", "tool.py", "--force"],
    )
    assert remove_result.exit_code == 0, remove_result.output

    import_result = runner.invoke(
        cli,
        ["--config", str(config_path), "import", str(export_file), "--force"],
    )
    assert import_result.exit_code == 0, import_result.output

    state_manager = StateManager(state_file)
    script = state_manager.get_script("tool.py")
    assert script is not None
    assert script.source_type == SourceType.LOCAL
    assert script.dependencies == []

    symlink_path = install_dir / "tool.py"
    assert symlink_path.exists()
    assert symlink_path.is_symlink()


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

    # Create uncommitted local changes.
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
    assert "Yes" in result.output


def test_cli_list_verbose_falls_back_on_narrow_width_when_enabled(tmp_path: Path, monkeypatch) -> None:
    """list --verbose should fallback to non-verbose output on narrow terminals when enabled."""
    runner = CliRunner()

    repo_dir = tmp_path / "repos"
    install_dir = tmp_path / "bin"
    state_file = tmp_path / "state.json"
    config_path = tmp_path / "config.toml"
    _write_config(
        config_path,
        repo_dir,
        install_dir,
        state_file,
        list_verbose_fallback=True,
        list_min_width=200,
    )

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

    result = runner.invoke(cli, ["--config", str(config_path), "list", "--verbose"])

    assert result.exit_code == 0, result.output
    assert "Warning:" in result.output
    assert "too narrow" in result.output
    assert "Falling back" in result.output
    assert "minimum 200 columns" in result.output
    assert result.output.count("┳") == 3
    assert "Commit" not in result.output
    assert "Dependencies" not in result.output
    assert "tool.py" in result.output


def test_cli_list_verbose_no_fallback_on_narrow_width_by_default(tmp_path: Path, monkeypatch) -> None:
    """list --verbose should remain verbose by default, even on narrow terminals."""
    runner = CliRunner()

    repo_dir = tmp_path / "repos"
    install_dir = tmp_path / "bin"
    state_file = tmp_path / "state.json"
    config_path = tmp_path / "config.toml"
    _write_config(config_path, repo_dir, install_dir, state_file, list_min_width=200)

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

    result = runner.invoke(cli, ["--config", str(config_path), "list", "--verbose"])

    assert result.exit_code == 0, result.output
    assert "Falling back" not in result.output
    assert result.output.count("┳") == 6
    assert "Commit" in result.output
    assert "Dependenci" in result.output
    assert "tool.py" in result.output


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

    # Create uncommitted local changes.
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

    result = runner.invoke(cli, ["--config", str(config_path), "list", "--verbose"])

    assert result.exit_code == 0, result.output
    assert "Local" in result.output
    assert "changes" in result.output
    assert "tool.py" in result.output
    assert "Yes" in result.output


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

    # Emulate uv-managed script content changes only.
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
    assert "No (managed)" in result.output


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

    # Emulate uv-managed script content changes only.
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

    result = runner.invoke(cli, ["--config", str(config_path), "list", "--verbose"])

    assert result.exit_code == 0, result.output
    assert "Local" in result.output
    assert "changes" in result.output
    assert "No" in result.output
    assert "(managed)" in result.output


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
    assert "pinned to v1.0.0" not in result.output
    assert "Updated" in result.output

    updated = StateManager(state_file).get_script("tool.py")
    assert updated is not None
    assert updated.ref == "v1.0.0"
    assert updated.ref_type == "tag"
    assert updated.dependencies == []
    assert (updated.repo_path / "tool.py").exists()


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
def test_cli_export_preserves_git_ref_metadata_and_import_dry_run_uses_it(tmp_path: Path) -> None:
    """Export/import dry-run should preserve and use branch/tag/commit ref metadata."""
    runner = CliRunner()

    repo_dir = tmp_path / "repos"
    install_dir = tmp_path / "bin"
    state_file = tmp_path / "state.json"
    config_path = tmp_path / "config.toml"
    _write_config(config_path, repo_dir, install_dir, state_file)

    state_manager = StateManager(state_file)
    state_manager.add_script(
        ScriptInfo(
            name="branch.py",
            source_type=SourceType.GIT,
            source_url="https://github.com/org/repo",
            ref="main",
            ref_type="branch",
            installed_at=datetime.now(),
            repo_path=repo_dir / "branch",
            commit_hash="11111111",
        )
    )
    state_manager.add_script(
        ScriptInfo(
            name="tag.py",
            source_type=SourceType.GIT,
            source_url="https://github.com/org/repo",
            ref="v1.2.3",
            ref_type="tag",
            installed_at=datetime.now(),
            repo_path=repo_dir / "tag",
            commit_hash="22222222",
        )
    )
    state_manager.add_script(
        ScriptInfo(
            name="commit.py",
            source_type=SourceType.GIT,
            source_url="https://github.com/org/repo",
            ref="deadbeef",
            ref_type="commit",
            installed_at=datetime.now(),
            repo_path=repo_dir / "commit",
            commit_hash="deadbeef",
        )
    )

    export_file = tmp_path / "git-export.json"
    export_result = runner.invoke(
        cli,
        ["--config", str(config_path), "export", "-o", str(export_file)],
    )
    assert export_result.exit_code == 0, export_result.output

    exported = json.loads(export_file.read_text(encoding="utf-8"))
    scripts_by_name = {item["name"]: item for item in exported["scripts"]}

    assert scripts_by_name["branch.py"]["source"] == "https://github.com/org/repo"
    assert scripts_by_name["branch.py"]["ref"] == "main"
    assert scripts_by_name["branch.py"]["ref_type"] == "branch"

    assert scripts_by_name["tag.py"]["ref"] == "v1.2.3"
    assert scripts_by_name["tag.py"]["ref_type"] == "tag"

    assert scripts_by_name["commit.py"]["ref"] == "deadbeef"
    assert scripts_by_name["commit.py"]["ref_type"] == "commit"

    dry_run_result = runner.invoke(
        cli,
        ["--config", str(config_path), "import", str(export_file), "--dry-run"],
    )
    assert dry_run_result.exit_code == 0, dry_run_result.output
    assert "#main" in dry_run_result.output
    assert "@v1.2.3" in dry_run_result.output
    assert "@deadbeef" in dry_run_result.output


@REQUIRES_UV
@REQUIRES_UV_HELPER
@pytest.mark.parametrize(
    ("shell", "marker"),
    [
        ("bash", "_uv_helper_completion"),
        ("zsh", "#compdef uv-helper"),
        ("fish", "function _uv_helper_completion"),
    ],
)
def test_cli_completion_outputs_non_empty_script(tmp_path: Path, shell: str, marker: str) -> None:
    """Completion command should emit shell script content for all shells."""
    runner = CliRunner()

    repo_dir = tmp_path / "repos"
    install_dir = tmp_path / "bin"
    state_file = tmp_path / "state.json"
    config_path = tmp_path / "config.toml"
    _write_config(config_path, repo_dir, install_dir, state_file)

    result = runner.invoke(cli, ["--config", str(config_path), "completion", shell])

    assert result.exit_code == 0, result.output
    assert result.output.strip()
    assert marker in result.output


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
