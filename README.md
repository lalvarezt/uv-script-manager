# UV Script Manager

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![CI](https://github.com/lalvarezt/uv-script-manager/workflows/CI/badge.svg)](https://github.com/lalvarezt/uv-script-manager/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A CLI tool to install and manage standalone Python scripts from Git repositories or local directories that lack
`setup.py` or `pyproject.toml` files.

## Overview

UV Script Manager bridges a critical gap in [uv](https://github.com/astral-sh/uv)'s functionality by enabling you to install and
manage Python scripts directly from Git repositories that don't have proper packaging configuration.

### The Problem

Many useful Python scripts exist in Git repositories without `setup.py` or `pyproject.toml` files. Currently, `uv`
cannot directly install these scripts. Users must:

- Clone repositories manually
- Navigate directories
- Run `uv add --script` commands
- Modify shebangs
- Create symlinks
- Track installations manually

### The Solution

This tool automates this entire workflow:

```bash
# Install a script directly from any Git repository
uv-script-manager install https://github.com/user/repo --script script.py

# That's it! The script is now available in your `PATH`
script.py --help
```

## Features

- **Direct Git Installation**: Install scripts from any Git repository (GitHub, GitLab, Bitbucket, self-hosted) with one
command
- **Local Directory Support**: Install scripts from local directories on your filesystem
- **Script Aliasing**: Install scripts with custom names using the `--alias` flag
- **Git Refs Support**: Install from specific branches, tags, or commits (pinned refs are preserved during updates)
- **Dependency Management**: `requirements.txt` support including `-r` includes, `-e` editable installs, direct URL
  requirements, extras, and version specifiers
- **Local Package Dependencies**: Add local packages as dependencies with automatic path management
- **Idempotent Operations**: Re-running installs updates instead of failing
- **State Tracking**: Keep track of all installed scripts
- **Export/Import**: Backup and restore script installations
- **Browse Repositories**: List available scripts in a repository before installing
- **Shell Completion**: Tab completion for `bash`, `zsh`, and `fish`
- **Rich CLI**: Beautiful terminal output with progress bars and tables
- **Configuration**: Customize behavior via TOML config files
- **Update Management**: Update individual scripts or all at once
- **Auto-Migration**: Database schema automatically migrates when upgrading

## Installation

### Using `uv` (Recommended)

```bash
uv tool install uv-script-manager
uv-script-manager --version
```

### From Source

```bash
git clone https://github.com/lalvarezt/uv-script-manager
cd uv-script-manager
uv pip install -e .
```

### Prerequisites

- Python 3.11 or higher
- [uv](https://github.com/astral-sh/uv) installed and in `PATH`
- [git](https://git-scm.com/) installed and in `PATH` when working with Git sources (local-only operations do not require
`git`)

## Quick Start

```bash
# Basic installation
uv-script-manager install https://github.com/user/repo --script script.py

# Install from a local directory (no git required)
uv-script-manager install ./tools --script app.py

# Install with dependencies
uv-script-manager install https://github.com/user/repo --script script.py --with requests,click

# List installed scripts
uv-script-manager list

# Update a specific script
uv-script-manager update script.py

# Update all scripts
uv-script-manager update --all

# Remove a script
uv-script-manager remove script.py
```

## Command Reference

### `install`

Install Python scripts from a Git repository or local directory.

```bash
uv-script-manager install <source> [--script <script.py> ...] [OPTIONS]
```

**Arguments:**

- `source`: Git repository URL or local directory path (Git URLs support `@tag`, `@commit`, `#branch` suffixes)

If `--script` is omitted in an interactive terminal, the CLI prompts you to select scripts from discovered
candidates. In non-interactive environments, `--script` is required.

**Options:**

- `-s, --script TEXT`: Script names to install (can be repeated)
- `--alias TEXT`: Custom name for the installed script (only for single script installations)
- `-w, --with TEXT`: Dependencies (`requirements.txt` path or comma-separated list, appends to existing dependencies)
- `-f, --force`: Force overwrite without confirmation
- `--no-symlink`: Skip creating symlinks
- `--no-deps`: Skip dependency resolution entirely
- `--install-dir PATH`: Custom installation directory
- `-v, --verbose`: Show dependency resolution details
- `--exact/--no-exact`: Use `--exact` flag in shebang for precise dependency management (default: from config)
- `--copy-parent-dir`: For local sources, copy entire parent directory instead of just the script
- `--add-source-package TEXT`: Add source as a local package dependency (optionally specify package name; for local
sources this requires `--copy-parent-dir`)

**Examples:**

```bash
# Basic installation from Git
uv-script-manager install https://github.com/user/repo --script script.py

# Install from local directory
uv-script-manager install /path/to/scripts --script app.py

# Install from local directory with full package copy
uv-script-manager install /path/to/mypackage --script cli.py --copy-parent-dir

# Install with local package as dependency
uv-script-manager install https://github.com/user/repo --script app.py --add-source-package=mylib

# With inline dependencies (appends to requirements.txt if present)
uv-script-manager install https://github.com/user/repo --script tool.py --with requests,click,rich

# Multiple scripts
uv-script-manager install https://github.com/user/repo \
  --script tool1.py \
  --script tool2.py --force

# Install with custom alias
uv-script-manager install https://github.com/user/repo --script long_script_name.py --alias short
# Now you can run: short --help

# Install without dependencies
uv-script-manager install https://github.com/user/repo --script standalone.py --no-deps
```

### `list`

List installed scripts.

```bash
uv-script-manager list [OPTIONS]
```

**Options:**

- `--verbose`, `-v`: Show detailed information (commit hash, local changes, and dependencies)
- `--tree`: Display scripts grouped by source in a tree view
- `--full`: Disable table-column truncation; long values wrap instead of using `…`
- `--source TEXT`: Filter by source URL/path substring
- `--status TEXT`: Filter by status (`local`, `git`, `pinned`, `needs-attention`, `clean`, `managed`, `unknown`)
- `--ref TEXT`: Filter Git refs by substring
- `--sort TEXT`: Sort by `name`, `updated`, `source`, or `status`
- `--json`: Output list as JSON

When values already fit, `uv-script-manager list --verbose` and `uv-script-manager list --verbose --full` can look the same.

**Examples:**

```bash
uv-script-manager list
uv-script-manager list --verbose
uv-script-manager list --verbose --full
uv-script-manager list --tree
uv-script-manager list --status pinned --sort updated
uv-script-manager list --json
```

### `show`

Show detailed information about an installed script.

```bash
uv-script-manager show <script-name> [--json]
```

**Arguments:**

- `script-name`: Name of the script to show (can be original name or alias)

**Options:**

- `--json`: Output script details as JSON

**Examples:**

```bash
uv-script-manager show script.py
uv-script-manager show short  # Show by alias
uv-script-manager show script.py --json
```

### `remove`

Remove an installed script.

```bash
uv-script-manager remove <script-name> [OPTIONS]
```

**Arguments:**

- `script-name`: Name of the script to remove (can be original name or alias)

**Options:**

- `-c, --clean-repo`: Remove cloned repository if no other scripts use it
- `-f, --force`: Skip confirmation prompt
- `--dry-run`: Preview removal without making changes

During removal the CLI reports the original source: Git installs show the repository URL, while
local installs show the stored source directory.

**Examples:**

```bash
uv-script-manager remove script.py
uv-script-manager remove short  # Remove by alias
uv-script-manager remove tool.py --clean-repo --force
uv-script-manager remove tool.py --dry-run
```

### `update`

Update an installed script.

```bash
uv-script-manager update [<script-name>] [OPTIONS]
```

**Arguments:**

- `script-name`: Name of the script to update (can be original name or alias)

**Options:**

- `-f, --force`: Force reinstall even if up-to-date
- `--all`: Update all installed scripts
- `--refresh-deps`: Re-resolve dependencies from the repository's `requirements.txt`
- `--exact/--no-exact`: Use `--exact` flag in shebang for precise dependency management (default: from config)
- `--dry-run`: Show what would be updated without applying changes
- `--json`: Output update results as JSON

Aliases are automatically preserved when updating scripts. Scripts installed from tags or commits are treated as pinned
and will not move to a different ref unless `--force` is used.

When using `--all`, local installations are skipped automatically (reported as `Local-only`) because the tool
needs access to the original source directory to refresh them. Pinned refs are reported as `Pinned (<ref>)` unless
`--force` or `--refresh-deps` is used. Dry-run output includes a `Local changes` column.

**Examples:**

```bash
uv-script-manager update script.py
uv-script-manager update short  # Update by alias
uv-script-manager update tool.py --force
uv-script-manager update --all
uv-script-manager update --all --dry-run
uv-script-manager update --all --dry-run --json
```

### `doctor`

Diagnose and repair installation issues.

```bash
uv-script-manager doctor [OPTIONS]
```

**Options:**

- `--repair`: Automatically repair state issues

Displays configuration paths, verifies system dependencies (`git`, `uv`), and validates the state database. Use
`--repair` to automatically fix common issues like missing directories or corrupted state.

**Examples:**

```bash
# Check system health
uv-script-manager doctor

# Check and auto-repair issues
uv-script-manager doctor --repair
```

### `browse`

List available scripts in a repository before installing.

```bash
uv-script-manager browse <git-url> [OPTIONS]
```

**Arguments:**

- `git-url`: Git repository URL (supports `@tag`, `@commit`, `#branch` suffixes)

**Options:**

- `--all`: Show all Python files including typically excluded ones (tests, `__init__.py`, etc.)

For GitHub repositories, tries the GitHub API first for fast listing without cloning. If the API is unavailable or
fails, it falls back to cloning into a cached directory. For other repositories, it clones to a cached directory.

**Examples:**

```bash
# List installable scripts in a repository
uv-script-manager browse https://github.com/user/repo

# List scripts from a specific tag
uv-script-manager browse https://github.com/user/repo@v1.0.0

# Show all Python files including tests
uv-script-manager browse https://github.com/user/repo --all
```

### `export`

Export installed scripts to a JSON file for backup or sharing.

```bash
uv-script-manager export [OPTIONS]
```

**Options:**

- `-o`, `--output PATH`: Output file path (default: stdout)

**Examples:**

```bash
# Export to stdout
uv-script-manager export

# Export to a file
uv-script-manager export -o scripts-backup.json
```

### `import`

Import and reinstall scripts from an export file.

```bash
uv-script-manager import <file> [OPTIONS]
```

**Arguments:**

- `file`: Path to the export JSON file

**Options:**

- `--dry-run`: Preview what would be installed without making changes
- `-f, --force`: Force overwrite existing scripts

**Examples:**

```bash
# Preview what would be imported
uv-script-manager import scripts-backup.json --dry-run

# Import scripts from backup
uv-script-manager import scripts-backup.json

# Force overwrite existing scripts
uv-script-manager import scripts-backup.json --force
```

### `completion`

Generate shell completion scripts.

```bash
uv-script-manager completion <shell>
```

**Arguments:**

- `shell`: Shell type (`fish`, `bash`, or `zsh`)

Generates shell-specific completion scripts that provide context-aware suggestions including installed script names for
commands like `show`, `remove`, and `update`.

**Examples:**

```bash
# Fish shell
uv-script-manager completion fish > ~/.config/fish/completions/uv-script-manager.fish

# Bash
uv-script-manager completion bash > ~/.local/share/bash-completion/completions/uv-script-manager

# Zsh
uv-script-manager completion zsh > ~/.zfunc/_uv-script-manager
# Then add: fpath+=~/.zfunc && autoload -Uz compinit && compinit
```

## Configuration

Configuration uses TOML files. The default location is `~/.config/uv-script-manager/config.toml`.

### Configuration File

```toml
[meta]
schema_version = 1

[global.paths]
# Where to clone repositories
repo_dir = "~/.local/share/uv-script-manager"

# Where to create symlinks
install_dir = "~/.local/bin"

# Where to store state file
state_file = "~/.local/share/uv-script-manager/state.json"

[global.git]
# Git clone depth (1 for shallow clone)
clone_depth = 1

[global.install]
# Automatically create symlinks
auto_symlink = true

# Verify script works after installation
verify_after_install = true

# Make scripts executable
auto_chmod = true

# Use --exact flag in shebang for precise dependency management
use_exact_flag = true

[commands.list]
# Reserved for future list command options
```

### Custom Configuration

You can specify a custom configuration file:

```bash
# Via command-line flag
uv-script-manager --config /path/to/config.toml install ...

# Via environment variable
export UV_SCRIPT_MANAGER_CONFIG=/path/to/config.toml
uv-script-manager install ...
```

### Configuration Priority

1. `--config` CLI option (selects the config file explicitly)
2. `UV_SCRIPT_MANAGER_CONFIG` environment variable (when `--config` is not provided)
3. Default config path (`~/.config/uv-script-manager/config.toml`)
4. Defaults sourced from `src/uv_script_manager/config.toml`

At runtime, command options such as `--install-dir` and `--exact/--no-exact` override config values for that command.

## How It Works

The tool automates the following workflow:

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

It modifies script shebangs to use `uv`'s script runner with the `--exact` flag:

```python
#!/usr/bin/env -S uv run --exact --script
```

The `--exact` flag ensures that the script's auto-managed virtual environment precisely matches the dependencies
specified in the script's inline metadata. When you remove dependencies from a script, the virtual environment will be
automatically cleaned up on the next run.

This behavior can be controlled via the `use_exact_flag` configuration option or the `--exact/--no-exact` CLI flags.

## Development

### Setup Development Environment

```bash
# Clone repository
git clone https://github.com/lalvarezt/uv-script-manager
cd uv-script-manager

# Setup local virtual environment with dev dependencies
uv sync --group dev
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

MIT License - see `LICENSE` file for details.
