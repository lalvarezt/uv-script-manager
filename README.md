# UV-Helper

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![CI](https://github.com/lalvarezt/uv-helper/workflows/CI/badge.svg)](https://github.com/lalvarezt/uv-helper/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A CLI tool to install and manage standalone Python scripts from Git repositories or local directories that lack `setup.py` or `pyproject.toml` files.

## Overview

UV-Helper bridges a critical gap in [uv](https://github.com/astral-sh/uv)'s functionality by enabling you to install and manage Python scripts directly from Git repositories that don't have proper packaging configuration.

### The Problem

Many useful Python scripts exist in Git repositories without `setup.py` or `pyproject.toml` files. Currently, uv cannot directly install these scripts. Users must:

- Clone repositories manually
- Navigate directories
- Run `uv add --script` commands
- Modify shebangs
- Create symlinks
- Track installations manually

### The Solution

UV-Helper automates this entire workflow:

```bash
# Install a script directly from any Git repository
uv-helper install https://github.com/user/repo --script script.py

# That's it! The script is now available in your PATH
script.py --help
```

## Features

- **Direct Git Installation**: Install scripts from any Git repository (GitHub, GitLab, Bitbucket, self-hosted) with one command
- **Local Directory Support**: Install scripts from local directories on your filesystem
- **Git Refs Support**: Install from specific branches, tags, or commits
- **Dependency Management**: Automatically handle script dependencies
- **Local Package Dependencies**: Add local packages as dependencies with automatic path management
- **Idempotent Operations**: Re-running installs updates instead of failing
- **State Tracking**: Keep track of all installed scripts
- **Rich CLI**: Beautiful terminal output with progress bars and tables
- **Configuration**: Customize behavior via TOML config files
- **Update Management**: Update individual scripts or all at once
- **Auto-Migration**: Database schema automatically migrates when upgrading

## Installation

### Using uv (Recommended)

```bash
uv tool install uv-helper
```

### From Source

```bash
git clone https://github.com/lalvarezt/uv-helper
cd uv-helper
uv pip install -e .
```

### Prerequisites

- Python 3.11 or higher
- [uv](https://github.com/astral-sh/uv) installed and in PATH
- [git](https://git-scm.com/) installed and in PATH when working with Git sources (local-only
  operations do not require git)

## Quick Start

```bash
# Basic installation
uv-helper install https://github.com/user/repo --script script.py

# Install from a local directory (no git required)
uv-helper install ./tools --script app.py

# Install with dependencies
uv-helper install https://github.com/user/repo --script script.py --with requests,click

# List installed scripts
uv-helper list

# Update a specific script
uv-helper update script.py

# Update all scripts
uv-helper update-all

# Remove a script
uv-helper remove script.py
```

## Command Reference

### `install`

Install Python scripts from a Git repository.

```bash
uv-helper install <git-url> --script <script.py> [--script <more.py> ...] [OPTIONS]
```

**Arguments:**

- `source`: Git repository URL or local directory path (Git URLs support `@tag`, `#branch` suffixes)

**Options:**

- `--script TEXT`: Script names to install (can be repeated)
- `--with TEXT`: Dependencies (`requirements.txt` path or comma-separated list, appends to existing dependencies)
- `--force`: Force overwrite without confirmation
- `--no-symlink`: Skip creating symlinks
- `--install-dir PATH`: Custom installation directory
- `--exact/--no-exact`: Use `--exact` flag in shebang for precise dependency management (default: from config)
- `--copy-parent-dir`: For local sources, copy entire parent directory instead of just the script
- `--add-source-package TEXT`: Add source as a local package dependency (optionally specify package name)

**Examples:**

```bash
# Basic installation from Git
uv-helper install https://github.com/user/repo --script script.py

# Install from local directory
uv-helper install /path/to/scripts --script app.py

# Install from local directory with full package copy
uv-helper install /path/to/mypackage --script cli.py --copy-parent-dir

# Install with local package as dependency
uv-helper install https://github.com/user/repo --script app.py --add-source-package=mylib

# With inline dependencies (appends to requirements.txt if present)
uv-helper install https://github.com/user/repo --script tool.py --with requests,click,rich

# Multiple scripts
uv-helper install https://github.com/user/repo \
  --script tool1.py \
  --script tool2.py --force
```

### `list`

List installed scripts.

```bash
uv-helper list [OPTIONS]
```

**Options:**

- `--format TEXT`: Output format (table, json)
- `--verbose`: Show detailed information

**Examples:**

```bash
uv-helper list
uv-helper list --format json
uv-helper list --verbose
```

### `remove`

Remove an installed script.

```bash
uv-helper remove <script-name> [OPTIONS]
```

**Arguments:**

- `script-name`: Name of the script to remove

**Options:**

- `--clean-repo`: Remove cloned repository if no other scripts use it
- `--force`: Skip confirmation prompt

During removal the CLI reports the original source: Git installs show the repository URL, while
local installs show the stored source directory.

**Examples:**

```bash
uv-helper remove script.py
uv-helper remove tool.py --clean-repo --force
```

### `update`

Update an installed script.

```bash
uv-helper update <script-name> [OPTIONS]
```

**Arguments:**

- `script-name`: Name of the script to update

**Options:**

- `--force`: Force reinstall even if up-to-date
- `--exact/--no-exact`: Use `--exact` flag in shebang for precise dependency management (default: from config)

**Examples:**

```bash
uv-helper update script.py
uv-helper update tool.py --force
```

### `update-all`

Update all installed scripts.

```bash
uv-helper update-all [OPTIONS]
```

**Options:**

- `--force`: Force reinstall all scripts
- `--exact/--no-exact`: Use `--exact` flag in shebang for precise dependency management (default: from config)

Local installations are skipped automatically (reported as `skipped (local)`) because UV-Helper
needs access to the original source directory to refresh them.

**Examples:**

```bash
uv-helper update-all
```

## Configuration

UV-Helper uses TOML configuration files. The default location is `~/.config/uv-helper/config.toml`.

### Configuration File

```toml
[paths]
# Where to clone repositories
repo_dir = "~/.local/share/uv-helper"

# Where to create symlinks
install_dir = "~/.local/bin"

# Where to store state file
state_file = "~/.local/share/uv-helper/state.json"

[git]
# Git clone depth (1 for shallow clone)
clone_depth = 1

[install]
# Automatically create symlinks
auto_symlink = true

# Verify script works after installation
verify_after_install = true

# Make scripts executable
auto_chmod = true

# Use --exact flag in shebang for precise dependency management
use_exact_flag = true
```

### Custom Configuration

You can specify a custom configuration file:

```bash
# Via command-line flag
uv-helper --config /path/to/config.toml install ...

# Via environment variable
export UV_HELPER_CONFIG=/path/to/config.toml
uv-helper install ...
```

### Configuration Priority

1. Command-line flags (highest priority)
2. Environment variables
3. Custom config file (via `--config`)
4. Default config file (`~/.config/uv-helper/config.toml`)
5. Built-in defaults (lowest priority)

## How It Works

UV-Helper automates the following workflow:

**For Git sources:**

1. **Clone Repository**: Clones the Git repository (or updates if already cloned)
2. **Checkout Ref**: Checks out the specified branch, tag, or commit

**For local sources:**

1. **Copy Files**: Copies script files or entire directory to managed location

**Common steps:**
3. **Resolve Dependencies**: Parses requirements from `--with` flag (appending to auto-detected `requirements.txt`)
4. **Add Package Sources**: If `--add-source-package` is used, adds local package to dependencies and sources
5. **Process Script**: Adds dependency metadata to script inline metadata block
6. **Modify Shebang**: Replaces shebang with `#!/usr/bin/env -S uv run --exact --script`
7. **Create Symlink**: Creates symlink in `~/.local/bin` (or custom install directory)
8. **Track State**: Saves installation info to state file
9. **Auto-Migration**: Automatically runs database schema migrations when needed

### Shebang Transformation

UV-Helper modifies script shebangs to use uv's script runner with the `--exact` flag:

```python
#!/usr/bin/env -S uv run --exact --script
```

The `--exact` flag ensures that the script's auto-managed virtual environment precisely matches the dependencies specified in the script's inline metadata. When you remove dependencies from a script, the virtual environment will be automatically cleaned up on the next run.

This behavior can be controlled via the `use_exact_flag` configuration option or the `--exact/--no-exact` CLI flags.

## Development

### Setup Development Environment

```bash
# Clone repository
git clone https://github.com/lalvarezt/uv-helper
cd uv-helper

# Install with dev dependencies
uv tool install -e ".[dev]"

# Setup local virtual environment
uv sync
```

### Run Tests

```bash
# Run all tests
uv run pytest -v
```

### Code Quality

```bash
# Run linter, fix imports, format files, and run type checks in one go
uv run ruff check --fix --unsafe-fixes && uv run ruff check --select I --fix && uv run ruff format && uv run ty check

# Run linter with Ruff
uv run ruff check --fix --unsafe-fixes

# Run linter, fix import ordering with Ruff
uv run ruff check --select I --fix

# Format code with Ruff's formatter
uv run ruff format

# Type check the project with Ty
uv run ty check
```

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Ensure all tests pass
6. Submit a pull request

## License

MIT License - see LICENSE file for details.
