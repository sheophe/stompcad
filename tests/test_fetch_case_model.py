"""The case-model fetch helper: validation, extraction, and cache layout."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from tools.fetch_case_model import PART_PATTERN, cache_dir, check_part, extract, url_for


def _archive(path: Path, names: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for name, payload in names.items():
            zf.writestr(name, payload)
    return path


def test_a_catalogue_part_is_accepted_and_upper_cased():
    assert check_part("1590bb") == "1590BB"


def test_a_part_outside_the_catalogue_is_rejected_by_name():
    with pytest.raises(ValueError, match="1590ZZ"):
        check_part("1590ZZ")


def test_the_safety_pattern_rejects_path_traversal_independently_of_the_catalogue():
    assert PART_PATTERN.fullmatch("1590BB")
    assert not PART_PATTERN.fullmatch("../etc/passwd")
    assert not PART_PATTERN.fullmatch("1590BB/../x")
    assert not PART_PATTERN.fullmatch("1590BB;rm -rf /")


def test_the_url_names_the_part_archive():
    assert url_for("1590BB") == "https://www.hammfg.com/files/parts/stp/1590BB.zip"


def test_the_download_request_identifies_itself(monkeypatch):
    """hammfg.com answers urllib's default User-Agent with 403.

    Patched at urlopen rather than at download: patching download is what let
    this ship broken, because it mocks away the only line that talks to a server.
    """
    seen = {}

    class _Response:
        def read(self):
            return b"payload"

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def _urlopen(request, *args, **kwargs):
        seen["agent"] = request.get_header("User-agent")
        seen["url"] = request.full_url
        return _Response()

    from tools import fetch_case_model

    monkeypatch.setattr(fetch_case_model, "urlopen", _urlopen)

    assert fetch_case_model.download("https://example.invalid/x.zip") == b"payload"
    assert seen["agent"], "the request must carry a User-Agent"
    assert "aidrill" in seen["agent"]
    assert seen["url"] == "https://example.invalid/x.zip"


def test_cache_dir_is_home_cache_aidrill_cases_by_default(monkeypatch):
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)

    assert cache_dir() == Path.home() / ".cache" / "aidrill" / "cases"


def test_cache_dir_honours_xdg_cache_home(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))

    assert cache_dir() == tmp_path / "aidrill" / "cases"


def test_extract_writes_the_stp_into_the_cache_and_returns_its_path(tmp_path: Path):
    archive = _archive(tmp_path / "a.zip", {"1590BB.stp": b"ISO-10303-21;\n"})
    cache = tmp_path / "cache"

    result = extract(archive, "1590BB", cache)

    assert result == cache / "1590BB.stp"
    assert result.read_bytes() == b"ISO-10303-21;\n"


def test_extract_refuses_an_archive_entry_that_escapes_the_cache(tmp_path: Path):
    archive = _archive(tmp_path / "a.zip", {"../1590BB.stp": b"x"})

    with pytest.raises(ValueError, match="unsafe"):
        extract(archive, "1590BB", tmp_path / "cache")


def test_extract_reports_an_archive_with_no_matching_stp(tmp_path: Path):
    archive = _archive(tmp_path / "a.zip", {"1590BB.igs": b"x"})

    with pytest.raises(ValueError, match="no 1590BB.stp"):
        extract(archive, "1590BB", tmp_path / "cache")


def test_a_cached_model_is_not_downloaded_again(tmp_path: Path, monkeypatch):
    from tools import fetch_case_model

    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "1590BB.stp").write_bytes(b"cached")

    def explode(url: str) -> bytes:  # pragma: no cover - must not run
        raise AssertionError(f"downloaded {url} despite a cache hit")

    monkeypatch.setattr(fetch_case_model, "download", explode)
    code = fetch_case_model.main(["1590BB", "--cache-dir", str(cache)])

    assert code == 0


def test_main_prints_only_the_path(tmp_path: Path, monkeypatch, capsys):
    from tools import fetch_case_model

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("1590BB.stp", b"ISO-10303-21;\n")
    monkeypatch.setattr(fetch_case_model, "download", lambda url: buffer.getvalue())

    cache = tmp_path / "cache"
    code = fetch_case_model.main(["1590BB", "--cache-dir", str(cache)])

    assert code == 0
    assert capsys.readouterr().out == f"{cache / '1590BB.stp'}\n"
