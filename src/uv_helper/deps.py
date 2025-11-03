"""Dependency management for UV-Helper."""

from pathlib import Path


def parse_requirements_file(requirements_path: Path) -> list[str]:
    """
    Parse requirements.txt file.

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
    with open(requirements_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            # Skip comments and empty lines
            if line and not line.startswith("#"):
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
        repo_path: Path to repository

    Returns:
        List of dependency strings
    """
    # Case 1: Explicit --with flag
    if with_arg:
        # Check if it's a file path
        if with_arg.endswith(".txt") or "/" in with_arg or "\\" in with_arg:
            req_path = repo_path / with_arg
            try:
                return parse_requirements_file(req_path)
            except FileNotFoundError:
                # Try as absolute path
                req_path = Path(with_arg)
                return parse_requirements_file(req_path)
        else:
            # Treat as comma-separated list - append to auto-detected requirements
            dependencies = []

            # First, auto-detect requirements.txt in repo root
            auto_requirements = repo_path / "requirements.txt"
            if auto_requirements.exists():
                dependencies.extend(parse_requirements_file(auto_requirements))

            # Then append additional dependencies from --with
            dependencies.extend(parse_dependencies_string(with_arg))
            return dependencies

    # Case 2: Auto-detect requirements.txt in repo root
    auto_requirements = repo_path / "requirements.txt"
    if auto_requirements.exists():
        return parse_requirements_file(auto_requirements)

    # Case 3: No dependencies
    return []


def format_dependency_for_uv(dep: str) -> str:
    """
    Format dependency string for uv command.

    Args:
        dep: Dependency string (e.g., "requests>=2.31.0" or "click")

    Returns:
        Formatted dependency string
    """
    # UV accepts standard pip dependency specifiers
    return dep.strip()
