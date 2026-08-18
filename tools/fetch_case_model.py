"""Download, unzip and cache a Hammond STEP model, printing its path.

A stopgap: `aicad` will own downloading and caching, so the file is written to
be ported verbatim. The safety check is a self-contained pattern with no
`aidrill` import; the catalogue is consulted only to improve the error.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import tempfile
import zipfile
from collections.abc import Sequence
from pathlib import Path
from urllib.request import urlopen

__all__ = ["PART_PATTERN", "check_part", "url_for", "download", "extract", "main"]

#: The only shape a designator may take. This, not the catalogue, is what makes
#: URL and archive-path construction safe when the file is lifted out of here.
PART_PATTERN = re.compile(r"[0-9]{4}[A-Z0-9]{0,4}")

_BASE = "https://www.hammfg.com/files/parts/stp"
_DEFAULT_CACHE = Path.home() / ".cache" / "aidrill" / "cases"


def check_part(text: str) -> str:
    """Upper-case and validate a designator, by pattern then by catalogue."""
    part = text.strip().upper()
    if not PART_PATTERN.fullmatch(part):
        raise ValueError(f"{text!r} is not a part designator")
    try:
        from aidrill.enclosures import HAMMOND_1590
    except ImportError:  # pragma: no cover - only when lifted out of this repo
        return part
    if part not in {enclosure.part for enclosure in HAMMOND_1590}:
        raise ValueError(f"{part} is not a base designator in the Hammond 1590 catalogue")
    return part


def url_for(part: str) -> str:
    return f"{_BASE}/{part}.zip"


def download(url: str) -> bytes:
    """Fetch an archive. Separated so tests can replace it."""
    with urlopen(url) as response:  # noqa: S310 - fixed https host, pattern-checked path
        return bytes(response.read())


def extract(archive: Path, part: str, cache_dir: Path) -> Path:
    """Copy ``part``.stp out of ``archive`` into ``cache_dir``, rejecting escapes."""
    wanted = f"{part}.stp"
    with zipfile.ZipFile(archive) as zf:
        for entry in zf.namelist():
            name = Path(entry).name
            if Path(entry).is_absolute() or ".." in Path(entry).parts:
                raise ValueError(f"unsafe archive entry {entry!r}")
            if name.upper() != wanted.upper():
                continue
            cache_dir.mkdir(parents=True, exist_ok=True)
            target = cache_dir / wanted
            with zf.open(entry) as source, target.open("wb") as sink:
                shutil.copyfileobj(source, sink)
            return target
    raise ValueError(f"no {wanted} in {archive.name}")


def main(argv: Sequence[str] | None = None) -> int:
    """Print the cached path for one designator, downloading only on a miss."""
    parser = argparse.ArgumentParser(
        prog="fetch_case_model",
        description="Download and cache a Hammond STEP model; print its path.",
    )
    parser.add_argument("part", metavar="PART", help="base designator, e.g. 1590BB")
    parser.add_argument(
        "--cache-dir", metavar="DIR", type=Path, default=_DEFAULT_CACHE,
        help=f"where models are cached (default: {_DEFAULT_CACHE})",
    )
    args = parser.parse_args(argv)

    try:
        part = check_part(args.part)
    except ValueError as failure:
        print(f"fetch_case_model: error: {failure}", file=sys.stderr)
        return 2

    cached = args.cache_dir / f"{part}.stp"
    if cached.exists():
        print(cached)
        return 0

    try:
        payload = download(url_for(part))
    except OSError as failure:
        print(f"fetch_case_model: error: {failure}", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory() as scratch:
        archive = Path(scratch) / f"{part}.zip"
        archive.write_bytes(payload)
        try:
            print(extract(archive, part, args.cache_dir))
        except (ValueError, zipfile.BadZipFile) as failure:
            print(f"fetch_case_model: error: {failure}", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
