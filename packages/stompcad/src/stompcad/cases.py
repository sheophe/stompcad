"""Where enclosure models live, and how one that is missing arrives.

ADR-0007's stopgap downloader moved here: acquiring a model was never
``stompdrill``'s job, and two downloaders would be two answers to where a
model comes from. Every failure is one exception carrying the sentence a
finding states, because the caller is a run step that must say what went
wrong rather than raise something raw at a builder.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import zipfile
from http.client import HTTPException
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

__all__ = [
    "PART_PATTERN",
    "ModelUnavailable",
    "cache_dir",
    "check_part",
    "url_for",
    "download",
    "extract",
    "cached",
    "fetch",
    "acquire",
]

#: The only shape a designator may take. This, not the catalogue, is what makes
#: URL and archive-path construction safe.
PART_PATTERN = re.compile(r"[0-9]{4}[A-Z0-9]{0,4}")

_BASE = "https://www.hammfg.com/files/parts/stp"

#: hammfg.com refuses urllib's default User-Agent with a 403, so the request
#: names the tool. Not evasion: it is a truthful identifier, and a courtesy to
#: whoever reads the server log.
_USER_AGENT = "stompcad/0.1 (+https://www.hammfg.com/ case-model fetcher)"


class ModelUnavailable(Exception):
    """A model that cannot be had, worded as the run reports it."""


def cache_dir() -> Path:
    """Where models are cached: ``$XDG_CACHE_HOME/stompcad/cases``, or under ``~/.cache``.

    The sole owner of this location in the package. ``stompdrill``'s test
    helper spells the same published rule rather than importing this, because
    the dependency order forbids that package reaching this one.
    """
    root = os.environ.get("XDG_CACHE_HOME")
    base = Path(root) if root else Path.home() / ".cache"
    return base / "stompcad" / "cases"


def check_part(text: str) -> str:
    """Upper-case and validate a designator, by pattern then by catalogue."""
    part = text.strip().upper()
    if not PART_PATTERN.fullmatch(part):
        raise ValueError(f"{text!r} is not a part designator")
    from stompdrill.enclosures import HAMMOND_1590

    if part not in {enclosure.part for enclosure in HAMMOND_1590}:
        raise ValueError(f"{part} is not a base designator in the Hammond 1590 catalogue")
    return part


def url_for(part: str) -> str:
    return f"{_BASE}/{part}.zip"


def download(url: str) -> bytes:
    """Fetch an archive. Separated so tests can replace it."""
    request = Request(url, headers={"User-Agent": _USER_AGENT})
    with urlopen(request) as response:  # noqa: S310 - fixed host, pattern-checked path
        return bytes(response.read())


def extract(archive: Path, part: str, cache: Path) -> Path:
    """Copy ``part``.stp out of ``archive`` into ``cache``, rejecting escapes.

    Written beside its destination and renamed into place: a model that
    arrived half-written would be trusted by every later run, and two runs
    fetching one part must not meet in the middle of the same file.
    """
    wanted = f"{part}.stp"
    with zipfile.ZipFile(archive) as zf:
        for entry in zf.namelist():
            if Path(entry).is_absolute() or ".." in Path(entry).parts:
                raise ValueError(f"unsafe archive entry {entry!r}")
            if Path(entry).name.upper() != wanted.upper():
                continue
            cache.mkdir(parents=True, exist_ok=True)
            target = cache / wanted
            handle, scratch = tempfile.mkstemp(dir=cache, prefix=f".{wanted}.")
            try:
                with zf.open(entry) as source, os.fdopen(handle, "wb") as sink:
                    shutil.copyfileobj(source, sink)
                os.replace(scratch, target)
            except BaseException:
                Path(scratch).unlink(missing_ok=True)
                raise
            return target
    raise ValueError(f"no {wanted} in {archive.name}")


def cached(part: str, cache: Path | None = None) -> Path | None:
    """The model already cached for this part, if one is."""
    candidate = (cache or cache_dir()) / f"{part.strip().upper()}.stp"
    return candidate if candidate.is_file() else None


def fetch(part: str, cache: Path | None = None) -> Path:
    """Download this part's model into the cache, and return where it landed."""
    where = cache or cache_dir()
    try:
        checked = check_part(part)
    except ValueError as failure:
        raise ModelUnavailable(str(failure)) from failure
    url = url_for(checked)
    try:
        payload = download(url)
    except (OSError, URLError, HTTPException) as failure:
        # ``HTTPException`` is the base of ``IncompleteRead``, which is what a
        # body cut short of its declared length raises -- and it is neither an
        # ``OSError`` nor a ``URLError``, so a narrower catch lets exactly the
        # failure this promise is about escape unworded.
        raise ModelUnavailable(f"{url} could not be fetched: {failure}") from failure
    try:
        with tempfile.TemporaryDirectory() as scratch:
            archive = Path(scratch) / f"{checked}.zip"
            archive.write_bytes(payload)
            return extract(archive, checked, where)
    except (OSError, ValueError, zipfile.BadZipFile) as failure:
        raise ModelUnavailable(f"{url} holds no usable model: {failure}") from failure


def acquire(part: str, cache: Path | None = None) -> Path:
    """This part's model: the one in the cache, or one fetched into it now."""
    where = cache or cache_dir()
    found = cached(part, where)
    return found if found is not None else fetch(part, where)
