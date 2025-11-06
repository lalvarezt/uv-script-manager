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
GIT_SHORT_HASH_LENGTH = 7
GIT_RETRY_MAX_ATTEMPTS = 4
GIT_RETRY_BACKOFF_BASE = 2  # seconds
