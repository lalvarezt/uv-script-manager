"""Direct Python source URL handling."""

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlparse
from urllib.request import urlopen

from pathvalidate import ValidationError, validate_filename

from .utils import ensure_dir, validate_python_script

URL_DOWNLOAD_TIMEOUT = 30
URL_MAX_DOWNLOAD_SIZE = 10 * 1024 * 1024
UNSUPPORTED_URL_SOURCE = "Unsupported URL source: uvsm only installs Python source files ending in .py"


class URLSourceError(Exception):
    """Raised when a direct Python source URL cannot be downloaded or validated."""


@dataclass(frozen=True)
class DownloadedURLScript:
    """A validated URL download staged for atomic installation."""

    path: Path
    filename: str
    source_hash: str


def is_python_source_url(url: str) -> bool:
    """Return whether URL is a direct HTTP(S) Python source URL."""
    parsed = urlparse(url)
    return parsed.scheme.lower() in ("http", "https") and unquote(parsed.path).lower().endswith(".py")


def is_unsupported_python_file_url(url: str) -> bool:
    """Return whether URL clearly targets an unsupported Python artifact."""
    parsed = urlparse(url)
    if parsed.scheme.lower() not in ("http", "https"):
        return False
    suffix = Path(unquote(parsed.path)).suffix.lower()
    return suffix in {".pyc", ".pyo", ".pyz", ".so", ".pyd", ".dll", ".dylib", ".whl"}


def managed_url_directory(repo_dir: Path, url: str) -> Path:
    """Return deterministic managed directory for a source URL."""
    url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
    return repo_dir / f"url-{url_hash}"


def download_url_script(url: str, destination_dir: Path) -> DownloadedURLScript:
    """Download and validate a direct Python source URL into a temporary file."""
    if not is_python_source_url(url):
        raise URLSourceError(UNSUPPORTED_URL_SOURCE)

    ensure_dir(destination_dir)
    temp_path: Path | None = None
    try:
        with urlopen(url, timeout=URL_DOWNLOAD_TIMEOUT) as response:  # noqa: S310 - schemes validated
            final_url = response.geturl()
            final_parsed = urlparse(final_url)
            if final_parsed.scheme.lower() not in ("http", "https"):
                raise URLSourceError("URL redirect used an unsupported scheme")
            if not is_python_source_url(final_url):
                raise URLSourceError(UNSUPPORTED_URL_SOURCE)

            filename = Path(unquote(final_parsed.path)).name
            if not filename:
                raise URLSourceError("URL does not contain a script filename")
            try:
                validate_filename(filename, platform="auto")
            except ValidationError as e:
                raise URLSourceError(f"Invalid script filename '{filename}': {e}") from e

            content = response.read(URL_MAX_DOWNLOAD_SIZE + 1)
            if len(content) > URL_MAX_DOWNLOAD_SIZE:
                raise URLSourceError("URL source exceeds the 10 MiB download limit")

        fd, temp_name = tempfile.mkstemp(prefix=".uvsm-url-", suffix=".py", dir=destination_dir)
        temp_path = Path(temp_name)
        with os.fdopen(fd, "wb") as temp_file:
            temp_file.write(content)

        if not validate_python_script(temp_path):
            raise URLSourceError("Downloaded file is not a valid Python script")

        return DownloadedURLScript(
            path=temp_path,
            filename=filename,
            source_hash=hashlib.sha256(content).hexdigest(),
        )
    except URLSourceError:
        if temp_path:
            temp_path.unlink(missing_ok=True)
        raise
    except HTTPError as e:
        raise URLSourceError(f"HTTP error downloading URL source: {e.code} {e.reason}") from e
    except (URLError, TimeoutError) as e:
        raise URLSourceError(f"Failed to download URL source: {e}") from e
    except OSError as e:
        if temp_path:
            temp_path.unlink(missing_ok=True)
        raise URLSourceError(f"Failed to store URL source: {e}") from e
