"""Additional tests for script_installer edge/error branches."""

import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from uv_helper import script_installer
from uv_helper.constants import SCRIPT_VERIFICATION_TIMEOUT, SourceType
from uv_helper.state import ScriptInfo, StateManager


def test_process_script_dependencies_empty_list_returns_true() -> None:
    """Dependency processing should no-op and succeed when list is empty."""
    assert script_installer.process_script_dependencies(Path("/tmp/tool.py"), []) is True


def test_process_script_dependencies_raises_on_uv_error(monkeypatch) -> None:
    """Dependency processing should wrap uv failures as ScriptInstallerError."""

    def raise_called_process_error(cmd, **kwargs):
        raise subprocess.CalledProcessError(1, cmd, stderr="uv failed")

    monkeypatch.setattr(script_installer, "run_command", raise_called_process_error)

    with pytest.raises(script_installer.ScriptInstallerError, match="Failed to add dependencies"):
        script_installer.process_script_dependencies(Path("/tmp/tool.py"), ["requests"])


def test_modify_shebang_raises_on_empty_file(tmp_path: Path) -> None:
    """Shebang modifier should reject empty scripts."""
    script_path = tmp_path / "empty.py"
    script_path.write_text("", encoding="utf-8")

    with pytest.raises(script_installer.ScriptInstallerError, match="Script file is empty"):
        script_installer.modify_shebang(script_path)


def test_modify_shebang_wraps_decode_errors(tmp_path: Path) -> None:
    """Shebang modifier should wrap Unicode decode errors."""
    script_path = tmp_path / "invalid.py"
    script_path.write_bytes(b"\xff\xfe\x00")

    with pytest.raises(script_installer.ScriptInstallerError, match="Failed to modify shebang"):
        script_installer.modify_shebang(script_path)


def test_add_package_source_inserts_package_into_existing_sources_section(tmp_path: Path) -> None:
    """Package source helper should append package line under existing sources section."""
    script_path = tmp_path / "script.py"
    script_path.write_text(
        "# /// script\n# [tool.uv.sources]\n# existing = { path = \"/tmp/existing\" }\n# ///\nprint('hi')\n",
        encoding="utf-8",
    )

    pkg_dir = tmp_path / "pkg"
    pkg_dir.mkdir()

    script_installer.add_package_source(script_path, "newpkg", pkg_dir)

    content = script_path.read_text(encoding="utf-8")
    assert f'# newpkg = {{ path = "{pkg_dir.resolve()}" }}' in content


def test_check_shadows_system_command_detects_external_command(monkeypatch, tmp_path: Path) -> None:
    """Shadow checker should return existing command path outside target directory."""
    monkeypatch.setattr(script_installer.shutil, "which", lambda name: "/usr/bin/tool")

    shadow = script_installer.check_shadows_system_command("tool", tmp_path / "bin")
    assert shadow == "/usr/bin/tool"


def test_create_symlink_returns_shadow_warning(tmp_path: Path, monkeypatch) -> None:
    """Symlink creation should include shadow warning when command already exists."""
    script_path = tmp_path / "tool.py"
    script_path.write_text("print('ok')\n", encoding="utf-8")
    target_dir = tmp_path / "bin"

    monkeypatch.setattr(script_installer, "check_shadows_system_command", lambda *_args: "/usr/bin/tool")

    symlink_path, warning = script_installer.create_symlink(script_path, target_dir)

    assert symlink_path.exists()
    assert warning is not None
    assert "shadows existing command" in warning


def test_create_symlink_raises_when_unlink_fails_after_last_retry(tmp_path: Path, monkeypatch) -> None:
    """Symlink creation should raise if cleanup fails on final retry."""
    script_path = tmp_path / "tool.py"
    script_path.write_text("print('ok')\n", encoding="utf-8")

    monkeypatch.setattr(
        Path, "symlink_to", lambda self, target: (_ for _ in ()).throw(FileExistsError("exists"))
    )
    monkeypatch.setattr(
        Path, "unlink", lambda self, missing_ok=False: (_ for _ in ()).throw(OSError("no unlink"))
    )

    with pytest.raises(script_installer.ScriptInstallerError, match="Failed to remove existing file"):
        script_installer.create_symlink(script_path, tmp_path / "bin")


def test_create_symlink_raises_after_retry_exhaustion(tmp_path: Path, monkeypatch) -> None:
    """Symlink creation should fail after retry exhaustion when race persists."""
    script_path = tmp_path / "tool.py"
    script_path.write_text("print('ok')\n", encoding="utf-8")

    monkeypatch.setattr(
        Path, "symlink_to", lambda self, target: (_ for _ in ()).throw(FileExistsError("exists"))
    )
    monkeypatch.setattr(Path, "unlink", lambda self, missing_ok=False: None)

    with pytest.raises(script_installer.ScriptInstallerError, match="after 3 attempts"):
        script_installer.create_symlink(script_path, tmp_path / "bin")


def test_create_symlink_wraps_unexpected_oserror(tmp_path: Path, monkeypatch) -> None:
    """Symlink creation should wrap unexpected OSError failures."""
    script_path = tmp_path / "tool.py"
    script_path.write_text("print('ok')\n", encoding="utf-8")

    monkeypatch.setattr(
        Path, "symlink_to", lambda self, target: (_ for _ in ()).throw(OSError("permission denied"))
    )

    with pytest.raises(script_installer.ScriptInstallerError, match="Failed to create symlink"):
        script_installer.create_symlink(script_path, tmp_path / "bin")


def test_make_executable_wraps_chmod_error(tmp_path: Path, monkeypatch) -> None:
    """Executable flag helper should wrap chmod failures."""
    script_path = tmp_path / "tool.py"
    script_path.write_text("print('ok')\n", encoding="utf-8")

    monkeypatch.setattr(Path, "chmod", lambda self, mode: (_ for _ in ()).throw(OSError("chmod failed")))

    with pytest.raises(script_installer.ScriptInstallerError, match="Failed to make script executable"):
        script_installer.make_executable(script_path)


def test_verify_script_handles_timeout_and_file_errors(monkeypatch) -> None:
    """Script verification should return False on timeout and run errors."""

    def timeout_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=SCRIPT_VERIFICATION_TIMEOUT)

    monkeypatch.setattr(script_installer, "run_command", timeout_run)
    assert script_installer.verify_script(Path("/tmp/tool.py")) is False

    monkeypatch.setattr(
        script_installer,
        "run_command",
        lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError("missing")),
    )
    assert script_installer.verify_script(Path("/tmp/tool.py")) is False


def test_remove_script_installation_raises_when_script_missing(tmp_path: Path) -> None:
    """Removal helper should fail when script is not present in state."""
    state_manager = StateManager(tmp_path / "state.json")

    with pytest.raises(script_installer.ScriptInstallerError, match="not found in state"):
        script_installer.remove_script_installation("missing.py", state_manager)


def test_remove_script_installation_wraps_unlink_oserror(tmp_path: Path, monkeypatch) -> None:
    """Removal helper should wrap filesystem unlink errors."""
    state_manager = StateManager(tmp_path / "state.json")

    symlink_path = tmp_path / "bin" / "tool.py"
    symlink_path.parent.mkdir(parents=True, exist_ok=True)
    symlink_path.write_text("stub", encoding="utf-8")

    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    (repo_path / "tool.py").write_text("print('x')\n", encoding="utf-8")

    state_manager.add_script(
        ScriptInfo(
            name="tool.py",
            source_type=SourceType.LOCAL,
            installed_at=datetime.now(),
            repo_path=repo_path,
            symlink_path=symlink_path,
            source_path=tmp_path,
        )
    )

    original_unlink = Path.unlink

    def fail_unlink(self, missing_ok=False):
        if self == symlink_path:
            raise OSError("cannot unlink")
        return original_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", fail_unlink)

    with pytest.raises(script_installer.ScriptInstallerError, match="Failed to remove script"):
        script_installer.remove_script_installation("tool.py", state_manager)


def test_verify_uv_available_wraps_missing_binary(monkeypatch) -> None:
    """UV verification should wrap FileNotFoundError as ScriptInstallerError."""
    monkeypatch.setattr(
        script_installer,
        "run_command",
        lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError("uv")),
    )

    with pytest.raises(script_installer.ScriptInstallerError, match="UV is not installed"):
        script_installer.verify_uv_available()


def test_install_script_rejects_invalid_python_script(monkeypatch, tmp_path: Path) -> None:
    """install_script should raise when Python validation fails."""
    script_path = tmp_path / "bad.py"
    script_path.write_text("not python", encoding="utf-8")

    monkeypatch.setattr(script_installer, "validate_python_script", lambda path: False)

    with pytest.raises(script_installer.ScriptInstallerError, match="Invalid Python script"):
        script_installer.install_script(
            script_path, [], script_installer.InstallConfig(install_dir=tmp_path / "bin")
        )


def test_install_script_does_not_fail_when_verify_returns_false(monkeypatch, tmp_path: Path) -> None:
    """install_script should complete even when post-install verification fails."""
    script_path = tmp_path / "tool.py"
    script_path.write_text("print('ok')\n", encoding="utf-8")

    monkeypatch.setattr(script_installer, "validate_python_script", lambda path: True)
    monkeypatch.setattr(script_installer, "modify_shebang", lambda *args, **kwargs: True)
    monkeypatch.setattr(script_installer, "make_executable", lambda *args, **kwargs: True)
    monkeypatch.setattr(script_installer, "verify_script", lambda *args, **kwargs: False)

    symlink_path, warning = script_installer.install_script(
        script_path,
        [],
        script_installer.InstallConfig(
            install_dir=tmp_path / "bin",
            auto_chmod=True,
            auto_symlink=False,
            verify_after_install=True,
        ),
    )

    assert symlink_path is None
    assert warning is None
