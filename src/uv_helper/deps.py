"""Dependency management for UV-Helper."""

from pathlib import Path

import requirements
from pathvalidate import ValidationError, validate_filepath


def parse_requirements_file(requirements_path: Path) -> list[str]:
    """
    Parse requirements.txt file using requirements-parser library.

    Handles:
    - `-r` includes (recursive)
    - `-e` editable installs
    - URL/file requirements
    - Environment markers
    - Extras and version specifiers

    Notes:
    - `-c` constraints and index options are ignored (not installable dependencies)
    - Unnamed requirements (for example direct URLs) are preserved from the original line

    Args:
        requirements_path: Path to requirements.txt

    Returns:
        List of dependency strings

    Raises:
        FileNotFoundError: If requirements file doesn't exist
    """
    if not requirements_path.exists():
        raise FileNotFoundError(f"Requirements file not found: {requirements_path}")

    dependencies = []
    ignored_prefixes = ("-c", "--constraint", "--index-url", "--extra-index-url", "--find-links")

    with open(requirements_path, encoding="utf-8") as f:
        for req in requirements.parse(f):
            line = req.line.strip()
            if not line:
                continue
            if line.startswith(ignored_prefixes):
                continue
            dependencies.append(line)

    return dependencies


def parse_dependencies_string(deps_str: str) -> list[str]:
    """
    Parse comma-separated dependencies string.

    Args:
        deps_str: Comma-separated dependencies

    Returns:
        List of dependency strings
    """
    return [dep.strip() for dep in deps_str.split(",") if dep.strip()]


def resolve_dependencies(
    with_arg: str | None,
    repo_path: Path,
    fallback_path: Path | None = None,
) -> list[str]:
    """
    Resolve dependencies based on --with argument and auto-detection.

    Resolution order:
    1. If --with requirements.txt: parse file
    2. If --with lib1,lib2: append to auto-detected requirements.txt (if exists)
    3. Auto-detect requirements.txt in repo root
    4. Fallback to no dependencies

    Args:
        with_arg: Value from --with flag
        repo_path: Path to repository (primary search location)
        fallback_path: Optional secondary path to search (e.g., original source directory)

    Returns:
        List of dependency strings
    """
    search_roots: list[Path] = [repo_path]
    if fallback_path and fallback_path not in search_roots:
        search_roots.append(fallback_path)

    # Case 1: Explicit --with flag
    if with_arg:
        # Check if it's a file path
        if with_arg.endswith(".txt") or "/" in with_arg or "\\" in with_arg:
            # Validate the path to prevent path traversal
            try:
                validate_filepath(with_arg, platform="auto")
            except ValidationError as e:
                raise ValueError(f"Invalid requirements file path '{with_arg}': {e}") from e

            last_error: FileNotFoundError | None = None
            for root in search_roots:
                req_path = root / with_arg
                try:
                    return parse_requirements_file(req_path)
                except FileNotFoundError as exc:
                    last_error = exc

            # Try as absolute path last
            try:
                return parse_requirements_file(Path(with_arg))
            except FileNotFoundError as exc:
                last_error = exc

            if last_error:
                raise last_error
            raise FileNotFoundError(f"Requirements file not found: {with_arg}")
        else:
            # Treat as comma-separated list - append to auto-detected requirements
            dependencies = []

            # First, auto-detect requirements.txt in repo root
            for root in search_roots:
                auto_requirements = root / "requirements.txt"
                if auto_requirements.exists():
                    dependencies.extend(parse_requirements_file(auto_requirements))
                    break

            # Then append additional dependencies from --with
            dependencies.extend(parse_dependencies_string(with_arg))
            return dependencies

    # Case 2: Auto-detect requirements.txt in repo root
    for root in search_roots:
        auto_requirements = root / "requirements.txt"
        if auto_requirements.exists():
            return parse_requirements_file(auto_requirements)

    # Case 3: No dependencies
    return []
