"""Which files one emitter owes for one document, and what they are called.

A drill file and a printed template describe one machine setup, so a surface
gets one of each; a drill document and a cut model describe the whole job, so
they stay one file. Here rather than in either command line, because
``stompcad`` owes artefacts byte-identical to ``stompdrill``'s and two copies
of a naming rule is how that promise breaks.
"""

from __future__ import annotations

from pathlib import Path

from stompmodel.model import SURFACE_FACE, DrillData
from stompmodel.protocols import Emitter, Payload

__all__ = ["sibling", "artefacts"]


def sibling(path: Path, key: str) -> Path:
    """``tar-case.drl`` and ``left`` give ``tar-case-left.drl``.

    A sibling of the named path rather than a directory per surface: a builder
    reaches one folder of drill files, and the existing staged-write
    transaction covers the whole set with no second mechanism.
    """
    return path.with_name(f"{path.stem}-{key}{path.suffix}")


def artefacts(
    emitter: Emitter[DrillData], path: Path, data: DrillData
) -> list[tuple[Path, Payload]]:
    """Every path and payload ``emitter`` owes for ``data``, in surface order.

    A per-setup format is emitted from a projection onto one surface, so it
    needs no knowledge of walls at all. ``per_surface`` is read off the class
    rather than required by the protocol: a format that has never heard of a
    surface describes the whole job, which is the only safe default for one
    this file has never seen.
    """
    if not getattr(type(emitter), "per_surface", False):
        return [(path, emitter.emit(data))]
    return [
        (
            path if key == SURFACE_FACE else sibling(path, key),
            emitter.emit(data.for_surface(key)),
        )
        for key in data.surface_keys()
    ]
