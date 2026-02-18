"""Tests for deps module."""

from pathlib import Path

import pytest

from uv_script_manager.deps import (
    parse_dependencies_string,
    parse_requirements_file,
    resolve_dependencies,
)


class TestParseRequirementsFile:
    """Tests for parse_requirements_file function."""

    def test_parses_simple_requirements(self, tmp_path: Path) -> None:
        """Test parsing simple requirements."""
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("requests\nclick\nrich")

        result = parse_requirements_file(req_file)

        assert result == ["requests", "click", "rich"]

    def test_parses_requirements_with_versions(self, tmp_path: Path) -> None:
        """Test parsing requirements with versions."""
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("requests>=2.31.0\nclick==8.1.0\nrich~=13.0")

        result = parse_requirements_file(req_file)

        assert result == ["requests>=2.31.0", "click==8.1.0", "rich~=13.0"]

    def test_skips_comments(self, tmp_path: Path) -> None:
        """Test skipping comments."""
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("# This is a comment\nrequests\n# Another comment\nclick")

        result = parse_requirements_file(req_file)

        assert result == ["requests", "click"]

    def test_skips_empty_lines(self, tmp_path: Path) -> None:
        """Test skipping empty lines."""
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("requests\n\nclick\n\n")

        result = parse_requirements_file(req_file)

        assert result == ["requests", "click"]

    def test_handles_include_editable_url_and_ignores_non_install_directives(self, tmp_path: Path) -> None:
        """Test requirements parsing for includes/editables/URLs and ignored directives."""
        req_file = tmp_path / "requirements.txt"
        extra_file = tmp_path / "extra.txt"
        constraints_file = tmp_path / "constraints.txt"

        extra_file.write_text("requests>=2.31.0\n", encoding="utf-8")
        constraints_file.write_text("urllib3<3\n", encoding="utf-8")

        req_file.write_text(
            "\n".join(
                [
                    "-r extra.txt",
                    "-e git+https://github.com/pallets/click.git@main#egg=click",
                    "https://example.com/pkg-1.0.0-py3-none-any.whl",
                    "-c constraints.txt",
                    "--constraint constraints.txt",
                    "--index-url https://pypi.org/simple",
                    "--extra-index-url https://example.com/simple",
                    "--find-links https://example.com/wheels",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        result = parse_requirements_file(req_file)

        assert "requests>=2.31.0" in result
        assert "-e git+https://github.com/pallets/click.git@main#egg=click" in result
        assert "https://example.com/pkg-1.0.0-py3-none-any.whl" in result
        assert all(
            not dep.startswith(("-c", "--constraint", "--index-url", "--extra-index-url", "--find-links"))
            for dep in result
        )

    def test_file_not_found(self, tmp_path: Path) -> None:
        """Test FileNotFoundError for missing file."""
        req_file = tmp_path / "nonexistent.txt"

        with pytest.raises(FileNotFoundError):
            parse_requirements_file(req_file)


class TestParseDependenciesString:
    """Tests for parse_dependencies_string function."""

    def test_parses_comma_separated(self) -> None:
        """Test parsing comma-separated dependencies."""
        result = parse_dependencies_string("requests,click,rich")

        assert result == ["requests", "click", "rich"]

    def test_handles_spaces(self) -> None:
        """Test handling spaces."""
        result = parse_dependencies_string("requests, click, rich")

        assert result == ["requests", "click", "rich"]

    def test_handles_versions(self) -> None:
        """Test handling versions."""
        result = parse_dependencies_string("requests>=2.31.0,click==8.1.0")

        assert result == ["requests>=2.31.0", "click==8.1.0"]

    def test_empty_string(self) -> None:
        """Test empty string."""
        result = parse_dependencies_string("")

        assert result == []


class TestResolveDependencies:
    """Tests for resolve_dependencies function."""

    def test_with_requirements_file(self, tmp_path: Path) -> None:
        """Test with --with requirements.txt."""
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("requests\nclick")

        result = resolve_dependencies("requirements.txt", tmp_path)

        assert result == ["requests", "click"]

    def test_with_comma_separated(self, tmp_path: Path) -> None:
        """Test with --with comma-separated."""
        result = resolve_dependencies("requests,click", tmp_path)

        assert result == ["requests", "click"]

    def test_auto_detect_requirements(self, tmp_path: Path) -> None:
        """Test auto-detecting requirements.txt."""
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("requests\nclick")

        result = resolve_dependencies(None, tmp_path)

        assert result == ["requests", "click"]

    def test_no_dependencies(self, tmp_path: Path) -> None:
        """Test with no dependencies."""
        result = resolve_dependencies(None, tmp_path)

        assert result == []

    def test_with_file_path_in_repo(self, tmp_path: Path) -> None:
        """Test with file path relative to repo."""
        subdir = tmp_path / "deps"
        subdir.mkdir()
        req_file = subdir / "requirements.txt"
        req_file.write_text("requests")

        result = resolve_dependencies("deps/requirements.txt", tmp_path)

        assert result == ["requests"]

    def test_auto_detect_requirements_from_fallback(self, tmp_path: Path) -> None:
        """Test auto-detecting requirements.txt from fallback path."""
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        source_path = tmp_path / "source"
        source_path.mkdir()
        (source_path / "requirements.txt").write_text("requests\n")

        result = resolve_dependencies(None, repo_path, source_path)

        assert result == ["requests"]

    def test_with_requirements_path_from_fallback(self, tmp_path: Path) -> None:
        """Test resolving requirements path relative to fallback directory."""
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        source_path = tmp_path / "source"
        (source_path / "deps").mkdir(parents=True)
        (source_path / "deps" / "requirements.txt").write_text("click\n")

        result = resolve_dependencies("deps/requirements.txt", repo_path, source_path)

        assert result == ["click"]

    def test_with_comma_separated_appends_to_auto_detected_requirements(self, tmp_path: Path) -> None:
        """Comma-separated --with values should append to auto-detected requirements.txt."""
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("requests\n")

        result = resolve_dependencies("click,rich", tmp_path)

        assert result == ["requests", "click", "rich"]

    def test_with_absolute_requirements_path(self, tmp_path: Path) -> None:
        """Absolute requirements paths should be supported as a final fallback."""
        req_file = tmp_path / "shared-requirements.txt"
        req_file.write_text("rich\n")

        unrelated_repo = tmp_path / "repo"
        unrelated_repo.mkdir()

        result = resolve_dependencies(str(req_file), unrelated_repo)

        assert result == ["rich"]

    def test_with_requirements_path_not_found_raises_file_not_found(self, tmp_path: Path) -> None:
        """Missing requirements path should raise FileNotFoundError after all fallbacks."""
        repo_path = tmp_path / "repo"
        repo_path.mkdir()

        with pytest.raises(FileNotFoundError):
            resolve_dependencies("deps/missing.txt", repo_path)

    def test_with_invalid_requirements_path_raises_value_error(self, tmp_path: Path) -> None:
        """Invalid requirements paths should raise ValueError from path validation."""
        with pytest.raises(ValueError, match="Invalid requirements file path"):
            resolve_dependencies("bad\x00path.txt", tmp_path)
