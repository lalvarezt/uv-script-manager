"""Tests for deps module."""

from pathlib import Path

import pytest

from uv_helper.deps import (
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
