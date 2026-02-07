"""CLI completion and interactive selection tests."""

from datetime import datetime
from pathlib import Path

import click
import pytest
from click.testing import CliRunner

from tests.cli_helpers import REQUIRES_UV, REQUIRES_UV_HELPER, _write_config
from uv_helper.cli import (
    _parse_script_selection,
    _prompt_for_script_selection,
    cli,
    complete_script_names,
)
from uv_helper.constants import SourceType
from uv_helper.state import ScriptInfo, StateManager


def test_complete_script_names_includes_alias_from_context(tmp_path: Path, monkeypatch) -> None:
    """Shell completion should include script aliases from loaded state."""
    from uv_helper.config import load_config

    repo_dir = tmp_path / "repos"
    install_dir = tmp_path / "bin"
    state_file = tmp_path / "state.json"
    config_path = tmp_path / "config.toml"
    _write_config(config_path, repo_dir, install_dir, state_file)

    config = load_config(config_path)
    state_manager = StateManager(state_file)
    state_manager.add_script(
        ScriptInfo(
            name="tool.py",
            source_type=SourceType.LOCAL,
            installed_at=datetime.now(),
            repo_path=repo_dir / "tool",
            source_path=tmp_path,
            symlink_path=install_dir / "short",
        )
    )

    ctx = click.Context(cli)
    ctx.obj = {"config": config}

    alias_matches = complete_script_names(ctx, param=click.Option(["--x"]), incomplete="sh")
    name_matches = complete_script_names(ctx, param=click.Option(["--x"]), incomplete="to")

    assert [item.value for item in alias_matches] == ["short"]
    assert [item.help for item in alias_matches] == ["alias for tool.py"]
    assert [item.value for item in name_matches] == ["tool.py"]


def test_complete_script_names_returns_empty_on_internal_error(monkeypatch) -> None:
    """Completion helper should fail closed and return empty list."""
    ctx = click.Context(cli)
    ctx.obj = None

    def raise_error() -> Path:
        raise RuntimeError("boom")

    monkeypatch.setattr("uv_helper.cli.get_config_path", raise_error)

    assert complete_script_names(ctx, param=click.Option(["--x"]), incomplete="x") == []


def test_parse_script_selection_accepts_ranges_and_rejects_invalid_values() -> None:
    """Selection parser should support ranges and reject malformed input."""
    assert _parse_script_selection("1,3-4,2", 5) == [1, 3, 4, 2]

    with pytest.raises(ValueError, match="Invalid range"):
        _parse_script_selection("4-2", 5)
    with pytest.raises(ValueError, match="Selection out of range"):
        _parse_script_selection("6", 5)
    with pytest.raises(ValueError, match="No selections provided"):
        _parse_script_selection(", ,", 5)


def test_prompt_for_script_selection_retries_until_valid(monkeypatch) -> None:
    """Interactive script prompt should continue until valid input is provided."""
    responses = iter(["nope", "1-2"])
    monkeypatch.setattr("uv_helper.cli.click.prompt", lambda *args, **kwargs: next(responses))

    selected = _prompt_for_script_selection(["a.py", "b.py", "c.py"])

    assert selected == ("a.py", "b.py")


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
