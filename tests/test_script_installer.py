"""Tests for script_installer module."""

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from uv_script_manager import script_installer


class DummyCompletedProcess(SimpleNamespace):
    """Simple stand-in for subprocess.CompletedProcess."""


def test_process_script_dependencies_invokes_uv(monkeypatch) -> None:
    """process_script_dependencies should call uv add with provided dependencies."""
    commands: list[list[str]] = []

    def fake_run_command(cmd: list[str], **_: object) -> DummyCompletedProcess:
        commands.append(cmd)
        return DummyCompletedProcess(returncode=0)

    monkeypatch.setattr(script_installer, "run_command", fake_run_command)

    script_path = Path("/tmp/tool.py")
    deps = ["requests", "click>=8.0"]

    result = script_installer.process_script_dependencies(script_path, deps)

    assert result is True
    assert commands == [
        ["uv", "add", "--script", str(script_path), "requests", "click>=8.0"],
    ]


def test_modify_shebang_sets_exact_flag(tmp_path: Path) -> None:
    """modify_shebang should enforce uv shebang with --exact by default."""
    script_path = tmp_path / "tool.py"
    script_path.write_text("print('hello')\n", encoding="utf-8")

    script_installer.modify_shebang(script_path, use_exact=True)

    first_line = script_path.read_text(encoding="utf-8").splitlines()[0]
    assert first_line == "#!/usr/bin/env -S uv run --exact --script"


def test_modify_shebang_without_exact(tmp_path: Path) -> None:
    """modify_shebang should omit --exact when requested."""
    script_path = tmp_path / "tool.py"
    script_path.write_text("#!/usr/bin/env python3\nprint('hello')\n", encoding="utf-8")

    script_installer.modify_shebang(script_path, use_exact=False)

    content = script_path.read_text(encoding="utf-8").splitlines()
    assert content[0] == "#!/usr/bin/env -S uv run --script"


def test_install_script_sets_permissions_and_symlink(tmp_path: Path, monkeypatch) -> None:
    """install_script should make script executable, adjust shebang, and create symlink."""
    script_path = tmp_path / "tool.py"
    script_path.write_text("print('hello')\n", encoding="utf-8")
    install_dir = tmp_path / "bin"

    dependency_calls: list[list[str]] = []

    def fake_process_dependencies(path: Path, deps: list[str]) -> bool:
        dependency_calls.append(deps.copy())
        assert path == script_path
        return True

    monkeypatch.setattr(
        script_installer,
        "process_script_dependencies",
        fake_process_dependencies,
    )
    monkeypatch.setattr(script_installer, "verify_script", lambda _: True)

    install_config = script_installer.InstallConfig(
        install_dir=install_dir,
        auto_chmod=True,
        auto_symlink=True,
        verify_after_install=True,
        use_exact=True,
    )
    symlink_path, shadow_warning = script_installer.install_script(
        script_path,
        ["requests"],
        install_config,
    )

    assert dependency_calls == [["requests"]]
    assert symlink_path == install_dir / "tool.py"
    assert symlink_path is not None
    assert symlink_path.exists()
    assert symlink_path.is_symlink()
    assert symlink_path.resolve() == script_path
    assert shadow_warning is None  # No system command should be shadowed

    first_line = script_path.read_text(encoding="utf-8").splitlines()[0]
    assert first_line == "#!/usr/bin/env -S uv run --exact --script"
    assert os.access(script_path, os.X_OK)


def test_add_package_source_creates_metadata_block(tmp_path: Path) -> None:
    """Test that add_package_source creates metadata block if missing."""
    script_path = tmp_path / "tool.py"
    script_path.write_text("#!/usr/bin/env python3\nprint('hello')\n", encoding="utf-8")
    package_path = tmp_path / "mypackage"
    package_path.mkdir()

    result = script_installer.add_package_source(script_path, "mypackage", package_path)

    assert result is True
    content = script_path.read_text(encoding="utf-8")
    assert "# /// script" in content
    assert "# ///" in content
    assert "# [tool.uv.sources]" in content
    assert f'# mypackage = {{ path = "{package_path.resolve()}" }}' in content


def test_add_package_source_adds_to_existing_block(tmp_path: Path) -> None:
    """Test that add_package_source adds to existing metadata block."""
    script_path = tmp_path / "tool.py"
    script_path.write_text(
        "#!/usr/bin/env python3\n# /// script\n# dependencies = ['requests']\n# ///\nprint('hello')\n",
        encoding="utf-8",
    )
    package_path = tmp_path / "mylib"
    package_path.mkdir()

    result = script_installer.add_package_source(script_path, "mylib", package_path)

    assert result is True
    content = script_path.read_text(encoding="utf-8")
    lines = content.splitlines()
    # Should have metadata block
    assert "# /// script" in lines
    assert "# [tool.uv.sources]" in content
    assert f'# mylib = {{ path = "{package_path.resolve()}" }}' in content
    # Should preserve existing dependencies
    assert "# dependencies = ['requests']" in content


def test_add_package_source_creates_sources_section(tmp_path: Path) -> None:
    """Test that [tool.uv.sources] section is created if missing."""
    script_path = tmp_path / "script.py"
    script_path.write_text(
        "# /// script\n# requires-python = '>=3.11'\n# ///\nprint('test')\n",
        encoding="utf-8",
    )
    package_path = tmp_path / "pkg"
    package_path.mkdir()

    script_installer.add_package_source(script_path, "pkg", package_path)

    content = script_path.read_text(encoding="utf-8")
    assert "# [tool.uv.sources]" in content
    assert f'# pkg = {{ path = "{package_path.resolve()}" }}' in content


def test_add_package_source_updates_existing_package(tmp_path: Path) -> None:
    """Test that existing package source is updated with new path."""
    old_path = tmp_path / "old"
    old_path.mkdir()
    script_path = tmp_path / "script.py"
    script_path.write_text(
        "# /// script\n"
        "# [tool.uv.sources]\n"
        f'# mypackage = {{ path = "{old_path}" }}\n'
        "# ///\n"
        "print('test')\n",
        encoding="utf-8",
    )

    new_path = tmp_path / "new"
    new_path.mkdir()

    script_installer.add_package_source(script_path, "mypackage", new_path)

    content = script_path.read_text(encoding="utf-8")
    # Should have new path
    assert f'# mypackage = {{ path = "{new_path.resolve()}" }}' in content
    # Should not have old path
    assert f'# mypackage = {{ path = "{old_path}" }}' not in content


def test_add_package_source_uses_absolute_path(tmp_path: Path) -> None:
    """Test that add_package_source converts to absolute path."""
    script_path = tmp_path / "script.py"
    script_path.write_text("print('hello')\n", encoding="utf-8")

    # Use a relative-looking path (though tmp_path is absolute)
    package_path = tmp_path / "subdir" / ".." / "mypackage"
    (tmp_path / "mypackage").mkdir()

    script_installer.add_package_source(script_path, "mypackage", package_path)

    content = script_path.read_text(encoding="utf-8")
    # Should have resolved absolute path (without ..)
    resolved = package_path.resolve()
    assert f'# mypackage = {{ path = "{resolved}" }}' in content
    assert ".." not in content


def test_add_package_source_preserves_shebang(tmp_path: Path) -> None:
    """Test that add_package_source doesn't affect shebang line."""
    script_path = tmp_path / "script.py"
    shebang = "#!/usr/bin/env python3"
    script_path.write_text(f"{shebang}\nprint('hello')\n", encoding="utf-8")
    package_path = tmp_path / "pkg"
    package_path.mkdir()

    script_installer.add_package_source(script_path, "pkg", package_path)

    lines = script_path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == shebang


def test_add_package_source_handles_file_error(tmp_path: Path) -> None:
    """Test that add_package_source raises ScriptInstallerError on file errors."""
    script_path = tmp_path / "nonexistent.py"
    package_path = tmp_path / "pkg"
    package_path.mkdir()

    with pytest.raises(script_installer.ScriptInstallerError):
        script_installer.add_package_source(script_path, "pkg", package_path)
