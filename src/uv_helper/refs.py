"""Shared helpers for source URLs and Git reference suffixes."""

import re
from typing import Literal

RefType = Literal["branch", "tag", "commit", "default"]

COMMIT_HASH_PATTERN = re.compile(r"[0-9a-fA-F]{7,40}")


def is_commit_hash(value: str) -> bool:
    """Return True when value looks like a Git commit hash."""
    return COMMIT_HASH_PATTERN.fullmatch(value) is not None


def infer_ref_type(ref: str | None) -> RefType:
    """Infer reference type from a raw ref value."""
    if not ref:
        return "default"
    if is_commit_hash(ref):
        return "commit"
    if ref.startswith("v") and len(ref) > 1 and ref[1].isdigit():
        return "tag"
    if ref[0].isdigit():
        return "tag"
    return "branch"


def split_source_ref(source: str) -> tuple[str, RefType, str | None]:
    """Split a source URL/path into base URL, ref type, and ref value."""
    if "#" in source:
        base_url, ref_value = source.rsplit("#", 1)
        return base_url, "branch", ref_value

    at_index = source.rfind("@")
    if at_index != -1 and at_index > max(source.rfind("/"), source.rfind(":")):
        base_url = source[:at_index]
        ref_value = source[at_index + 1 :]
        ref_type: RefType = "commit" if is_commit_hash(ref_value) else "tag"
        return base_url, ref_type, ref_value

    return source, "default", None


def build_ref_suffix(ref: str, ref_type: str | None) -> str:
    """Build URL ref suffix preserving import/export compatibility."""
    if ref_type == "branch":
        return f"#{ref}"
    if ref_type in ("tag", "commit"):
        return f"@{ref}"

    inferred = infer_ref_type(ref)
    if inferred in ("tag", "commit"):
        return f"@{ref}"
    return f"#{ref}"
