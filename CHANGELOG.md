# Changelog

All notable changes to UV-Helper will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.3.0] - 2025-11-10

### Added

- **Script aliasing support**: New `--alias` flag for `install` command allows custom naming of installed scripts
- `get_script_by_symlink()` method in StateManager to search scripts by their symlink/alias name
- Alias preservation during script updates (both Git and local sources)
- Support for using aliases in `remove` and `update` commands
- Display of aliases in `list` command output (normal mode shows alias, verbose shows "alias -> original_name")

### Changed

- Git short SHA length increased from 7 to 8 characters for better uniqueness
- `list` command now displays symlink names (aliases) instead of original script filenames
- `list --verbose` shows relationship between alias and original name when they differ
- `remove` and `update` commands now accept both original script names and aliases
- Rename the column header from `Installed` to `Updated` to accurately reflect this behavior
- Updated CLI documentation with alias usage examples

## [1.2.1] - 2025-11-06

### Added

- GitHub Actions CI/CD workflow for automated testing and quality checks
- `commands/` module with dedicated handler classes (`InstallHandler`, `UpdateHandler`, `RemoveHandler`)
- `display.py` module for display logic separation
- `constants.py` module for centralized constant definitions
- `migrations/` directory with modular migration structure
- Runtime Python version check at CLI entry point
- `SourceType` enum for type-safe source type handling

### Fixed

- Git is now optional for local-only script operations
- `copy_parent_dir` flag now properly persisted and used for local script updates
- Database path access now uses explicit parameter passing instead of private attribute access
- Improved dependency resolution for non-Git workflows

### Changed

- Refactored `cli.py` from 851 lines to 346 lines (59% reduction)
- Extracted command logic into focused handler classes
- Reorganized migration system into modular directory structure
- Improved code organization with constants and enums
- Enhanced test coverage with 960+ new test lines across multiple modules

## [1.2.0] - 2025-11-03

### Added

- **Local directory installation support**: Install scripts from local filesystem directories, not just Git repositories
- `--copy-parent-dir` flag: Copy entire parent directory instead of just the script file
- `--add-source-package` flag: Add source directory as a local package dependency with automatic path management
- Database migration system: Automatic schema migrations on version upgrades
- Support for both Git and local sources in all commands

### Fixed

- `--with` flag now appends to existing `requirements.txt` instead of replacing it
- Improved Python script validation using `ast.parse()` instead of naive first-line checking
- Script validation now accepts any valid Python syntax (docstrings, comments, etc.)

### Changed

- Updated README with local directory installation examples and usage
- Enhanced `install` command help text with local source examples
- Added code comments explaining metadata table usage in migrations

## [1.1.0] - 2025-11-03

### Added

- Support for `--exact` flag in shebang lines for precise dependency management
- New `use_exact_flag` configuration option (default: `true`)
- CLI flags `--exact/--no-exact` for `install`, `update`, and `update-all` commands

### Changed

- Default shebang now includes `--exact` flag: `#!/usr/bin/env -S uv run --exact --script`
- Updated documentation with new configuration option and CLI flags

## [1.0.0] - 2025-10-29

### Added

- Initial public release of UV-Helper with CLI commands to install, list, update, and remove scripts sourced from Git repositories lacking packaging metadata.
- Support for Git refs (branches, tags, commits) and automatic cloning/updating with configurable clone depth.
- Dependency management via the `--with` flag and automatic detection of `requirements.txt` files.
- Configurable installation workflow using TOML-based settings for repository/bin directories, symlink creation, verification, and permissions.
- State tracking powered by TinyDB and Pydantic models to record script metadata, enabling idempotent operations and update checks.
- Rich terminal experience implemented with Click and Rich, including progress indicators, tables, and considerate error reporting.
