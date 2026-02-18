"""CLI import/export command integration tests."""

import json
from datetime import datetime
from pathlib import Path

from click.testing import CliRunner

from tests.cli_helpers import REQUIRES_UV, _write_config
from uv_script_manager.cli import cli
from uv_script_manager.constants import SourceType
from uv_script_manager.state import ScriptInfo, StateManager


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


def test_cli_export_no_scripts_and_import_input_validation(tmp_path: Path, monkeypatch) -> None:
    """export/import should cover empty state and invalid input structures."""
    runner = CliRunner()
    repo_dir = tmp_path / "repos"
    install_dir = tmp_path / "bin"
    state_file = tmp_path / "state.json"
    config_path = tmp_path / "config.toml"
    _write_config(config_path, repo_dir, install_dir, state_file)

    monkeypatch.setattr("uv_script_manager.cli.verify_uv_available", lambda: True)

    export_result = runner.invoke(cli, ["--config", str(config_path), "export"])
    assert export_result.exit_code == 0, export_result.output
    assert "No scripts installed." in export_result.output

    invalid_json = tmp_path / "invalid.json"
    invalid_json.write_text("{not-json", encoding="utf-8")
    invalid_json_result = runner.invoke(
        cli,
        ["--config", str(config_path), "import", str(invalid_json)],
    )
    assert invalid_json_result.exit_code != 0
    assert "Invalid JSON file" in invalid_json_result.output

    missing_key = tmp_path / "missing-key.json"
    missing_key.write_text(json.dumps({"version": 1}), encoding="utf-8")
    missing_key_result = runner.invoke(
        cli,
        ["--config", str(config_path), "import", str(missing_key)],
    )
    assert missing_key_result.exit_code != 0
    assert "missing 'scripts' key" in missing_key_result.output

    empty_scripts = tmp_path / "empty-scripts.json"
    empty_scripts.write_text(json.dumps({"version": 1, "scripts": []}), encoding="utf-8")
    empty_scripts_result = runner.invoke(
        cli,
        ["--config", str(config_path), "import", str(empty_scripts)],
    )
    assert empty_scripts_result.exit_code == 0, empty_scripts_result.output
    assert "No scripts to import." in empty_scripts_result.output


def test_cli_import_handles_missing_entries_and_install_errors(tmp_path: Path, monkeypatch) -> None:
    """import should keep going when entries are incomplete or install fails."""
    runner = CliRunner()
    repo_dir = tmp_path / "repos"
    install_dir = tmp_path / "bin"
    state_file = tmp_path / "state.json"
    config_path = tmp_path / "config.toml"
    _write_config(config_path, repo_dir, install_dir, state_file)

    monkeypatch.setattr("uv_script_manager.cli.verify_uv_available", lambda: True)

    def fail_install(self, source, scripts, request):
        raise ValueError("install failed")

    monkeypatch.setattr("uv_script_manager.cli.InstallHandler.install", fail_install)

    import_file = tmp_path / "import.json"
    import_file.write_text(
        json.dumps(
            {
                "version": 1,
                "scripts": [
                    {"name": "missing-source"},
                    {"source": "https://github.com/acme/repo"},
                    {
                        "name": "branchy.py",
                        "source_type": "git",
                        "source": "https://github.com/acme/repo",
                        "ref": "feature/new-ui",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        cli,
        ["--config", str(config_path), "import", str(import_file)],
    )

    assert result.exit_code == 0, result.output
    assert "Missing name or source" in result.output
    assert "install failed" in result.output


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
