"""Tests for direct Python source URL handling."""

import hashlib
from pathlib import Path

import pytest

from uv_script_manager.url_source import (
    UNSUPPORTED_URL_SOURCE,
    URLSourceError,
    download_url_script,
    is_python_source_url,
    is_unsupported_python_file_url,
    managed_url_directory,
)


class FakeResponse:
    """Minimal urllib response for download tests."""

    def __init__(self, content: bytes, final_url: str) -> None:
        self.content = content
        self.final_url = final_url

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        return None

    def geturl(self) -> str:
        return self.final_url

    def read(self, size: int) -> bytes:
        return self.content[:size]


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://example.com/tool.py", True),
        ("https://example.com/tool.PY?raw=1#fragment", True),
        ("http://example.com/tool.py", True),
        ("ftp://example.com/tool.py", False),
        ("https://example.com/tool.pyc", False),
        ("https://example.com/repo", False),
    ],
)
def test_is_python_source_url(url: str, expected: bool) -> None:
    assert is_python_source_url(url) is expected


@pytest.mark.parametrize("suffix", [".pyc", ".pyo", ".pyz", ".so", ".pyd", ".dll", ".dylib", ".whl"])
def test_unsupported_python_artifact_urls(suffix: str) -> None:
    assert is_unsupported_python_file_url(f"https://example.com/tool{suffix}")


def test_download_url_script_uses_final_filename_and_hash(tmp_path: Path, monkeypatch) -> None:
    content = b"print('ok')\n"
    monkeypatch.setattr(
        "uv_script_manager.url_source.urlopen",
        lambda *args, **kwargs: FakeResponse(content, "https://cdn.example.com/final.py"),
    )

    downloaded = download_url_script("https://example.com/original.py", tmp_path)

    assert downloaded.filename == "final.py"
    assert downloaded.source_hash == hashlib.sha256(content).hexdigest()
    assert downloaded.path.read_bytes() == content


def test_download_url_script_rejects_non_python_redirect(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "uv_script_manager.url_source.urlopen",
        lambda *args, **kwargs: FakeResponse(b"<html></html>", "https://example.com/page.html"),
    )

    with pytest.raises(URLSourceError, match=UNSUPPORTED_URL_SOURCE):
        download_url_script("https://example.com/tool.py", tmp_path)


def test_download_url_script_rejects_oversized_response(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "uv_script_manager.url_source.URL_MAX_DOWNLOAD_SIZE",
        4,
    )
    monkeypatch.setattr(
        "uv_script_manager.url_source.urlopen",
        lambda *args, **kwargs: FakeResponse(b"12345", "https://example.com/tool.py"),
    )

    with pytest.raises(URLSourceError, match="10 MiB"):
        download_url_script("https://example.com/tool.py", tmp_path)


def test_managed_url_directory_is_deterministic(tmp_path: Path) -> None:
    url = "https://example.com/tool.py"
    expected = hashlib.sha256(url.encode()).hexdigest()[:12]
    assert managed_url_directory(tmp_path, url) == tmp_path / f"url-{expected}"
