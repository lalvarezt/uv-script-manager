"""Constants used throughout UV-Helper."""

from enum import Enum


# Source types
class SourceType(str, Enum):
    """Script source types.

    Attributes:
        GIT: Script installed from Git repository
        LOCAL: Script installed from local filesystem
    """

    GIT = "git"
    LOCAL = "local"


# Script inline metadata markers (PEP 723)
SCRIPT_METADATA_START = "# /// script"
SCRIPT_METADATA_END = "# ///"
SCRIPT_METADATA_SOURCES_SECTION = "# [tool.uv.sources]"

# Default shebang configurations
SHEBANG_UV_RUN_EXACT = "#!/usr/bin/env -S uv run --exact --script\n"
SHEBANG_UV_RUN = "#!/usr/bin/env -S uv run --script\n"

# Script verification timeout (seconds)
SCRIPT_VERIFICATION_TIMEOUT = 10.0

# Database table names
DB_TABLE_SCRIPTS = "scripts"
DB_TABLE_METADATA = "metadata"

# Metadata keys
METADATA_KEY_SCHEMA_VERSION = "schema_version"

# Database metadata document ID (fixed ID for schema version tracking)
DB_METADATA_DOC_ID = 1

# JSON output formatting
JSON_OUTPUT_INDENT = 2

# Git configuration
GIT_SHORT_HASH_LENGTH = 8
GIT_RETRY_MAX_ATTEMPTS = 4
GIT_RETRY_BACKOFF_BASE = 2  # seconds

# Script installer configuration
SYMLINK_CREATION_MAX_ATTEMPTS = 3  # Maximum attempts for atomic symlink creation
SYMLINK_CREATION_RETRY_DELAY = 0.1  # Delay between symlink retries (seconds)

# Progress spinner configuration
PROGRESS_SPINNER_TRANSIENT = True  # Whether spinner disappears after completion
PROGRESS_SPINNER_REFRESH_RATE = 10  # Spinner refresh rate (Hz)

# File permissions
SCRIPT_EXECUTABLE_MODE = 0o100  # Owner-only executable permission

# Validation limits
MAX_SCRIPT_NAME_LENGTH = 255  # Maximum script filename length
MAX_DEPENDENCY_COUNT = 1000  # Maximum dependencies per script

# State management
STATE_VALIDATION_ON_STARTUP = True  # Whether to validate state on startup

# Network timeouts
NETWORK_OPERATION_TIMEOUT = 30.0  # Default timeout for network operations (seconds)
GIT_CLONE_TIMEOUT = 300.0  # Timeout for git clone (5 minutes)

# Logging configuration
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
