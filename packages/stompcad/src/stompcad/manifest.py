"""The project file: declared intent, beside the artwork, named from it.

Spec decisions 8 and 9. One object per configuration place, keyed by the
place's own name, plus a schema version. The panel itself is absent: the
manifest is named after it, so recording it would be a second answer to a
question the filename already settles.

Paths are stored relative to this file's own directory. An absolute path
would survive exactly until the project was moved or shared, and a project
that stops working when it is copied is not a project file.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from stompmodel.errors import StompError

__all__ = [
    "MANIFEST_SUFFIX",
    "VERSION",
    "PLACES",
    "ManifestError",
    "Manifest",
    "manifest_path",
    "read",
]

#: What the project file is called, given the artwork's stem.
MANIFEST_SUFFIX = ".stompcad.json"

#: The schema this version writes. An older reader meeting a newer file
#: keeps the keys it knows, which is what makes a bump additive.
VERSION = 1

#: Each place, and the fields it may declare. The single statement of the
#: schema: ``read`` filters against it, ``fill`` writes against it, and a
#: field added to ``settings`` without a row here is never remembered.
PLACES: dict[str, frozenset[str]] = {
    "artwork": frozenset({"drill_layer", "reference_layer", "form_depth"}),
    "enclosure": frozenset({"case", "case_model", "case_face", "case_margin_mm"}),
    "drilling": frozenset({
        "grid_mm", "grid_warn_mm", "drill_standard", "drill_sizes",
        "no_drill_sizes", "title",
    }),
    "boards": frozenset({
        "boards", "panel_reference", "match_tolerance_mm",
        "seat_pitch_max_mm", "seat_pitch_min_mm",
    }),
    "output": frozenset({"targets"}),
}

#: Fields holding a path, or a list of them, which are stored relative to
#: the manifest and resolved against it on the way back in. ``output.targets``
#: is handled separately: it is stored as a mapping of format to path, so it
#: round-trips through its own branch rather than through these two shapes.
_PATHS: dict[str, frozenset[str]] = {
    "enclosure": frozenset({"case_model"}),
    "boards": frozenset({"boards"}),
}


class ManifestError(StompError):
    """A project file that cannot be read. Exit 3, naming the file.

    A ``StompError`` so ``cli.main`` catches it beside the library faults
    it already handles, rather than growing a second handler for the same
    outcome. Spec decision 9: a project whose declarations cannot be read
    must never be run under values that look like the user's own.
    """


@dataclass(frozen=True, slots=True)
class Manifest:
    """What a project declares, and what was passed over on the way in."""

    values: dict[str, dict[str, Any]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def manifest_path(panel: Path) -> Path:
    """The project file for one panel: beside it, named from its stem."""
    return panel.with_name(f"{panel.stem}{MANIFEST_SUFFIX}")


def read(panel: Path) -> Manifest:
    """This project's declarations, or an empty one where there is no file.

    An unknown key is a note rather than a refusal, which is what lets a
    file written by a later version still open. A file that is not an
    object, or not JSON at all, is refused: a manifest that cannot be
    understood must not be silently treated as absent.
    """
    path = manifest_path(panel)
    if not path.is_file():
        return Manifest()
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as failure:
        raise ManifestError(f"{path}: this project file cannot be read: {failure}") from failure
    if not isinstance(loaded, dict):
        raise ManifestError(f"{path}: a project file must be an object, not {type(loaded).__name__}")

    notes: list[str] = []
    version = loaded.pop("version", None)
    if isinstance(version, int) and version > VERSION:
        notes.append(
            f"{path.name} declares version {version}; this build reads version "
            f"{VERSION}, so any key it does not know is ignored"
        )
    values: dict[str, dict[str, Any]] = {}
    for place, declared in loaded.items():
        if place not in PLACES:
            notes.append(f"{path.name}: ignoring unknown section {place!r}")
            continue
        if not isinstance(declared, dict):
            raise ManifestError(f"{path}: section {place!r} must be an object")
        kept: dict[str, Any] = {}
        for key, value in declared.items():
            if key not in PLACES[place]:
                notes.append(f"{path.name}: ignoring unknown key {place}.{key}")
                continue
            kept[key] = _absolute(place, key, value, path.parent)
        if kept:
            values[place] = kept
    return Manifest(values, notes)


def _absolute(place: str, key: str, value: Any, root: Path) -> Any:
    """Resolve a stored path against the project, leaving other values alone.

    ``targets`` is a mapping in the file and a tuple of pairs in memory,
    because a format may appear once and the file should say so; the
    conversion belongs here, beside the one that wrote it.
    """
    if key == "targets" and isinstance(value, dict):
        return tuple((name, root / str(path)) for name, path in sorted(value.items()))
    if key not in _PATHS.get(place, frozenset()):
        return value
    if value is None:
        return None
    if isinstance(value, list):
        return [root / str(item) for item in value]
    return root / str(value)
