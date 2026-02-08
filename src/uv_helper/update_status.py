"""Shared status values for update command results."""

UPDATE_STATUS_UPDATED = "updated"
UPDATE_STATUS_UP_TO_DATE = "up-to-date"
UPDATE_STATUS_WOULD_UPDATE = "would update"
UPDATE_STATUS_WOULD_UPDATE_LOCAL_CHANGES = "would update (local custom changes present)"
UPDATE_STATUS_WOULD_UPDATE_LOCAL_CHANGES_LEGACY = "would update (local changes present)"
UPDATE_STATUS_SKIPPED_LOCAL = "skipped (local)"

UPDATE_STATUS_PINNED_PREFIX = "pinned to "
UPDATE_STATUS_ERROR_PREFIX = "Error: "


def make_pinned_status(ref: str) -> str:
    """Build a pinned-status message."""
    return f"{UPDATE_STATUS_PINNED_PREFIX}{ref}"


def parse_pinned_status(status: str) -> str | None:
    """Extract pinned ref from status, if present."""
    if status.startswith(UPDATE_STATUS_PINNED_PREFIX):
        return status.removeprefix(UPDATE_STATUS_PINNED_PREFIX)
    return None


def make_error_status(message: str) -> str:
    """Build an error status message."""
    return f"{UPDATE_STATUS_ERROR_PREFIX}{message}"


def is_error_status(status: str) -> bool:
    """Return True when status represents an error."""
    return status.startswith(UPDATE_STATUS_ERROR_PREFIX)
