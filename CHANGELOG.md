# Changelog

All notable changes to UV-Helper will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
