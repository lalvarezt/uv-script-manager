"""Install and update tests for direct Python source URLs."""

import hashlib
from datetime import datetime
from pathlib import Path

import pytest
from click.testing import CliRunner
from rich.console import Console

from tests.cli_helpers import _write_config
from uv_script_manager.cli import cli
from uv_script_manager.commands.install import InstallHandler, InstallRequest
from uv_script_manager.commands.update import UpdateHandler
from uv_script_manager.config import load_config
from uv_script_manager.constants import SourceType
from uv_script_manager.script_installer import ScriptInstallerError
from uv_script_manager.state import ScriptInfo, StateManager
from uv_script_manager.update_status import UPDATE_STATUS_UP_TO_DATE, UPDATE_STATUS_UPDATED, is_error_status
from uv_script_manager.url_source import DownloadedURLScript, URLSourceError


def _download(destination: Path, content: bytes, filename: str = "tool.py") -> DownloadedURLScript:
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / ".download.py"
    path.write_bytes(content)
    return DownloadedURLScript(path, filename, hashlib.sha256(content).hexdigest())


def _config(tmp_path: Path):
    config_path = tmp_path / "config.toml"
    _write_config(config_path, tmp_path / "repos", tmp_path / "bin", tmp_path / "state.json")
    return load_config(config_path)


def test_install_direct_url_persists_source_metadata(tmp_path: Path, monkeypatch) -> None:
    config = _config(tmp_path)
    content = b"print('v1')\n"
    monkeypatch.setattr(
        "uv_script_manager.commands.install.download_url_script",
        lambda url, destination: _download(destination, content),
    )
    monkeypatch.setattr(
        "uv_script_manager.commands.install.install_script",
        lambda path, dependencies, install_config: (None, None),
    )

    request = InstallRequest(None, True, True, None, False, None, False, None, None, True)
    result = InstallHandler(config, Console(record=True)).install("https://example.com/tool.py", (), request)

    assert result[0][1] is True
    script = StateManager(config.state_file).get_script("tool.py")
    assert script is not None
    assert script.source_type == SourceType.URL
    assert script.source_url == "https://example.com/tool.py"
    assert script.source_hash == hashlib.sha256(content).hexdigest()


def test_update_direct_url_compares_hash_and_reinstalls(tmp_path: Path, monkeypatch) -> None:
    config = _config(tmp_path)
    original = b"print('v1')\n"
    changed = b"print('v2')\n"
    monkeypatch.setattr(
        "uv_script_manager.commands.install.download_url_script",
        lambda url, destination: _download(destination, original),
    )
    monkeypatch.setattr(
        "uv_script_manager.commands.install.install_script",
        lambda path, dependencies, install_config: (None, None),
    )
    request = InstallRequest(None, True, True, None, False, None, False, None, None, True)
    InstallHandler(config, Console(record=True)).install("https://example.com/tool.py", (), request)

    monkeypatch.setattr(
        "uv_script_manager.commands.update.download_url_script",
        lambda url, destination: _download(destination, original),
    )
    updater = UpdateHandler(config, Console(record=True))
    assert updater.update("tool.py", False, None)[1] == UPDATE_STATUS_UP_TO_DATE

    monkeypatch.setattr(
        "uv_script_manager.commands.update.download_url_script",
        lambda url, destination: _download(destination, changed),
    )
    monkeypatch.setattr(
        "uv_script_manager.commands.update.install_script",
        lambda path, dependencies, install_config: (None, None),
    )
    assert updater.update("tool.py", False, None)[1] == UPDATE_STATUS_UPDATED

    script = StateManager(config.state_file).get_script("tool.py")
    assert script is not None
    assert script.source_hash == hashlib.sha256(changed).hexdigest()
    assert (script.repo_path / script.name).read_bytes() == changed


def test_update_direct_url_restores_previous_file_on_install_failure(tmp_path: Path, monkeypatch) -> None:
    config = _config(tmp_path)
    original = b"print('v1')\n"
    changed = b"print('v2')\n"
    monkeypatch.setattr(
        "uv_script_manager.commands.install.download_url_script",
        lambda url, destination: _download(destination, original),
    )
    monkeypatch.setattr(
        "uv_script_manager.commands.install.install_script",
        lambda path, dependencies, install_config: (None, None),
    )
    request = InstallRequest(None, True, True, None, False, None, False, None, None, True)
    InstallHandler(config, Console(record=True)).install("https://example.com/tool.py", (), request)

    monkeypatch.setattr(
        "uv_script_manager.commands.update.download_url_script",
        lambda url, destination: _download(destination, changed),
    )
    monkeypatch.setattr(
        "uv_script_manager.commands.update.install_script",
        lambda *args: (_ for _ in ()).throw(ScriptInstallerError("failed")),
    )

    result = UpdateHandler(config, Console(record=True)).update("tool.py", False, None)
    script = StateManager(config.state_file).get_script("tool.py")

    assert is_error_status(result[1])
    assert script is not None
    assert script.source_hash == hashlib.sha256(original).hexdigest()
    assert (script.repo_path / script.name).read_bytes() == original


def test_url_dry_run_rejects_redirected_filename_change(tmp_path: Path, monkeypatch) -> None:
    config = _config(tmp_path)
    content = b"print('ok')\n"
    script_dir = config.repo_dir / "url-test"
    script_dir.mkdir(parents=True)
    (script_dir / "tool.py").write_bytes(content)
    StateManager(config.state_file).add_script(
        ScriptInfo(
            name="tool.py",
            source_type=SourceType.URL,
            source_url="https://example.com/tool.py",
            source_hash=hashlib.sha256(content).hexdigest(),
            installed_at=datetime.now(),
            repo_path=script_dir,
        )
    )
    monkeypatch.setattr(
        "uv_script_manager.commands.update.download_url_script",
        lambda url, destination: _download(destination, content, "renamed.py"),
    )

    with pytest.raises(URLSourceError, match="filename changed"):
        UpdateHandler(config, Console(record=True)).update("tool.py", False, None, dry_run=True)


def test_cli_installs_direct_url_without_script_option(tmp_path: Path, monkeypatch) -> None:
    config = _config(tmp_path)
    content = b"print('ok')\n"
    monkeypatch.setattr("uv_script_manager.cli.verify_uv_available", lambda: None)
    monkeypatch.setattr(
        "uv_script_manager.commands.install.download_url_script",
        lambda url, destination: _download(destination, content),
    )
    monkeypatch.setattr(
        "uv_script_manager.commands.install.install_script",
        lambda path, dependencies, install_config: (None, None),
    )

    result = CliRunner().invoke(
        cli,
        ["--config", str(tmp_path / "config.toml"), "install", "https://example.com/tool.py", "--no-deps"],
    )

    assert result.exit_code == 0, result.output
    assert StateManager(config.state_file).get_script("tool.py") is not None


def test_cli_rejects_compiled_python_url(tmp_path: Path, monkeypatch) -> None:
    _config(tmp_path)
    monkeypatch.setattr("uv_script_manager.cli.verify_uv_available", lambda: None)

    result = CliRunner().invoke(
        cli,
        ["--config", str(tmp_path / "config.toml"), "install", "https://example.com/tool.pyc"],
    )

    assert result.exit_code == 1
    assert "only installs Python source files ending in" in result.output
    assert ".py" in result.output


@pytest.mark.parametrize(
    ("options", "message"),
    [
        (["--script", "tool.py"], "--script cannot be used with a direct .py URL"),
        (["--copy-parent-dir"], "--copy-parent-dir cannot be used with a direct .py URL"),
        (["--add-source-package", "tool"], "--add-source-package cannot be used with a direct .py URL"),
    ],
)
def test_cli_rejects_url_incompatible_options_before_download(
    tmp_path: Path, monkeypatch, options: list[str], message: str
) -> None:
    _config(tmp_path)
    monkeypatch.setattr("uv_script_manager.cli.verify_uv_available", lambda: None)
    monkeypatch.setattr(
        "uv_script_manager.commands.install.download_url_script",
        lambda *args: pytest.fail("invalid URL options must be rejected before download"),
    )

    result = CliRunner().invoke(
        cli,
        ["--config", str(tmp_path / "config.toml"), "install", "https://example.com/tool.py", *options],
    )

    assert result.exit_code == 1
    assert message in result.output
