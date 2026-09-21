"""The enclosure model cache: where it is, what it holds, and what it fetches.

A local HTTP server stands in for hammfg.com throughout. Nothing here reaches
the network, and the failures matter as much as the success: a model that
arrives half-written would be trusted by every later run.
"""

from __future__ import annotations

import http.server
import shutil
import threading
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Protocol

import pytest

from stompcad import cases
from stompcad.cases import PART_PATTERN

__all__: list[str] = []


class Serve(Protocol):
    """What the ``serve`` fixture hands back: publish these paths, get a base URL.

    Spelled as a protocol rather than a ``Callable`` because ``truncate`` is
    named at the one call site that wants a body cut short, and a bare
    ``Callable`` cannot carry a keyword argument.
    """

    def __call__(self, files: dict[str, bytes], truncate: bool = False) -> str: ...


def _archive(tmp_path: Path, name: str, member: str, payload: bytes = b"ISO-10303-21;\n") -> bytes:
    """A zip holding one named member, as the manufacturer's archives do."""
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(member, payload)
    return path.read_bytes()


@pytest.fixture
def agents() -> list[str]:
    """Every ``User-Agent`` the local server was handed, in the order it saw them."""
    return []


@pytest.fixture
def serve(agents: list[str]) -> Iterator[Serve]:
    """Serve a fixed set of paths, and return the base URL they live under."""
    held: dict[str, bytes] = {}
    #: Whether to promise a whole body and then send half of it, which is what a
    #: dropped connection looks like to a client that trusted Content-Length.
    cut = [False]

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - http.server's own spelling
            agents.append(self.headers.get("User-Agent", ""))
            body = held.get(self.path)
            if body is None:
                self.send_error(404, "no such part")
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body[: len(body) // 2] if cut[0] else body)

        def log_message(self, format: str, *args: object) -> None:
            return None

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def publish(files: dict[str, bytes], truncate: bool = False) -> str:
        held.clear()
        held.update(files)
        cut[0] = truncate
        host, port = server.socket.getsockname()[:2]
        return f"http://{host}:{port}"

    try:
        yield publish
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _at(monkeypatch: pytest.MonkeyPatch, base: str) -> None:
    """Point the module's URLs at the local server, path shape unchanged."""
    monkeypatch.setattr(cases, "_BASE", base)


def test_the_cache_is_under_xdg_cache_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    assert cases.cache_dir() == tmp_path / "stompcad" / "cases"


def test_the_cache_falls_back_to_the_home_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The published rule, which stompdrill's own test helper spells too."""
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert cases.cache_dir() == tmp_path / ".cache" / "stompcad" / "cases"


def test_a_cached_model_is_found_and_an_absent_one_is_not(tmp_path: Path) -> None:
    (tmp_path / "1590B.stp").write_text("ISO-10303-21;\n")
    assert cases.cached("1590B", tmp_path) == tmp_path / "1590B.stp"
    assert cases.cached("1590A", tmp_path) is None


def test_a_fetch_lands_the_model_in_the_cache(
    monkeypatch: pytest.MonkeyPatch, serve: Serve, tmp_path: Path
) -> None:
    base = serve({"/1590B.zip": _archive(tmp_path, "one.zip", "1590B.stp")})
    _at(monkeypatch, base)
    landed = cases.fetch("1590B", tmp_path / "cache")
    assert landed == tmp_path / "cache" / "1590B.stp"
    assert landed.read_bytes() == b"ISO-10303-21;\n"


def test_acquire_prefers_the_cache_and_never_asks_the_server(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The control: with the download replaced by a refusal, a hit still returns."""
    (tmp_path / "1590B.stp").write_text("ISO-10303-21;\n")

    def refuse(url: str) -> bytes:
        raise AssertionError(f"a cached part must not be fetched: {url}")

    monkeypatch.setattr(cases, "download", refuse)
    assert cases.acquire("1590B", tmp_path) == tmp_path / "1590B.stp"


def test_a_part_the_catalogue_does_not_list_is_refused_before_the_network(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def refuse(url: str) -> bytes:
        raise AssertionError(f"an unchecked part must not be fetched: {url}")

    monkeypatch.setattr(cases, "download", refuse)
    with pytest.raises(cases.ModelUnavailable, match="9999"):
        cases.fetch("9999", tmp_path)


def test_a_part_with_no_published_file_is_reported_with_its_url(
    monkeypatch: pytest.MonkeyPatch, serve: Serve, tmp_path: Path
) -> None:
    _at(monkeypatch, serve({}))
    with pytest.raises(cases.ModelUnavailable) as failure:
        cases.fetch("1590B", tmp_path)
    assert "1590B.zip" in str(failure.value)


def test_an_archive_without_the_model_is_reported(
    monkeypatch: pytest.MonkeyPatch, serve: Serve, tmp_path: Path
) -> None:
    _at(monkeypatch, serve({"/1590B.zip": _archive(tmp_path, "empty.zip", "readme.txt")}))
    with pytest.raises(cases.ModelUnavailable, match="1590B.stp"):
        cases.fetch("1590B", tmp_path / "cache")
    assert not (tmp_path / "cache" / "1590B.stp").exists()


def test_a_response_cut_off_mid_stream_is_reported_and_caches_nothing(
    monkeypatch: pytest.MonkeyPatch, serve: Serve, tmp_path: Path
) -> None:
    """The failure that really escapes: a truncated body raises IncompleteRead,
    whose base is HTTPException -- neither OSError nor URLError. A half-written
    model is worse than none, because every later run would trust it."""
    cache = tmp_path / "cache"
    cache.mkdir()
    whole = _archive(tmp_path, "one.zip", "1590B.stp")
    _at(monkeypatch, serve({"/1590B.zip": whole}, truncate=True))
    with pytest.raises(cases.ModelUnavailable, match="1590B.zip"):
        cases.fetch("1590B", cache)
    assert list(cache.iterdir()) == []


def test_a_download_that_never_starts_is_reported(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()

    def cut_off(url: str) -> bytes:
        raise OSError("connection reset by peer")

    monkeypatch.setattr(cases, "download", cut_off)
    with pytest.raises(cases.ModelUnavailable, match="connection reset"):
        cases.fetch("1590B", cache)
    assert list(cache.iterdir()) == []


def test_an_extraction_that_fails_part_way_leaves_nothing_behind(
    monkeypatch: pytest.MonkeyPatch, serve: Serve, tmp_path: Path
) -> None:
    """The same promise one layer down, where the bytes are actually written."""
    cache = tmp_path / "cache"
    _at(monkeypatch, serve({"/1590B.zip": _archive(tmp_path, "one.zip", "1590B.stp")}))

    def fail(source: object, sink: object, length: int = 0) -> None:
        raise OSError("no space left on device")

    # The same module object ``cases`` copies through, patched by its own name
    # here because a module is not something a package exports.
    monkeypatch.setattr(shutil, "copyfileobj", fail)
    with pytest.raises(cases.ModelUnavailable, match="no space"):
        cases.fetch("1590B", cache)
    assert not cache.exists() or list(cache.iterdir()) == []


def test_an_archive_naming_a_path_outside_the_cache_is_refused(
    monkeypatch: pytest.MonkeyPatch, serve: Serve, tmp_path: Path
) -> None:
    """The carried-over guard: an entry may name a file, never a place."""
    _at(monkeypatch, serve({"/1590B.zip": _archive(tmp_path, "evil.zip", "../../1590B.stp")}))
    with pytest.raises(cases.ModelUnavailable, match="unsafe"):
        cases.fetch("1590B", tmp_path / "cache")


def test_a_lower_case_designator_is_accepted_and_upper_cased() -> None:
    """The catalogue is spelled in capitals, and a builder's keyboard is not."""
    assert cases.check_part("1590bb") == "1590BB"


def test_the_safety_pattern_rejects_a_path_independently_of_the_catalogue() -> None:
    """The pattern, not the catalogue, is what makes a URL and an archive path safe."""
    assert PART_PATTERN.fullmatch("1590BB")
    assert not PART_PATTERN.fullmatch("../etc/passwd")
    assert not PART_PATTERN.fullmatch("1590BB/../x")
    assert not PART_PATTERN.fullmatch("1590BB;rm -rf /")


def test_the_url_names_the_part_archive_on_the_manufacturer_s_site() -> None:
    """Asserted unpatched, so the published address is what the module holds."""
    assert cases.url_for("1590BB") == "https://www.hammfg.com/files/parts/stp/1590BB.zip"


def test_the_download_request_identifies_itself(serve: Serve, agents: list[str]) -> None:
    """hammfg.com answers urllib's default User-Agent with 403.

    Driven through a real request to the local server rather than a stand-in
    for ``urlopen``: replacing the only line that talks to a server is what
    let this ship broken once already.
    """
    base = serve({"/1590B.zip": b"payload"})
    assert cases.download(f"{base}/1590B.zip") == b"payload"
    assert agents and "stompcad" in agents[-1]


def test_the_suite_s_own_guard_refuses_a_url_off_this_machine() -> None:
    """The standing control for ``conftest``'s ``no_downloads``.

    Every other test here reaches a local server, so none of them would
    notice that guard rotting open. This is what holds "no test reaches the
    network" to something that ships rather than to a run once by hand.
    """
    with pytest.raises(AssertionError, match="hammfg"):
        cases.download("https://www.hammfg.com/files/parts/stp/1590B.zip")


def test_the_guard_reads_the_host_rather_than_the_start_of_the_url() -> None:
    """A name merely beginning with the loopback address is somebody else's."""
    with pytest.raises(AssertionError):
        cases.download("http://127.0.0.1.example.com/1590B.zip")
    with pytest.raises(AssertionError):
        cases.download("http://localhost.example.com/1590B.zip")
