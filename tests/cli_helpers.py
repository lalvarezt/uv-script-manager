"""Shared helpers and markers for CLI integration tests."""

import shutil
import subprocess
from pathlib import Path

import pytest

REQUIRES_UV = pytest.mark.skipif(shutil.which("uv") is None, reason="uv command required")
REQUIRES_GIT = pytest.mark.skipif(shutil.which("git") is None, reason="git command required")
REQUIRES_UV_HELPER = pytest.mark.skipif(
    shutil.which("uv-script-manager") is None,
    reason="uv-script-manager executable required",
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
) -> None:
    config_path.write_text(
        "\n".join(
            [
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
        ),
        encoding="utf-8",
    )
