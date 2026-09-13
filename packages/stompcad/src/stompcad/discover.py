"""What a run can find out for itself, and the phrase naming how.

Spec decision 6, rank three. Discovery is stronger than a default and
weaker than a declaration, so nothing here overrides anything -- each
function returns what it found and lets ``pick`` decide whether it wins.

The designators a board carries are absent by design: they arrive with
``read boards``, so they are discovered by a run rather than before one.
"""

from __future__ import annotations

from pathlib import Path

from stompdrill.pipeline.enclosure import infer_part_name
from stompdrill.sources import AiPdfSource

from .settings import Discovery

__all__ = [
    "ARTEFACT_NAMES",
    "panels",
    "layers",
    "board_candidates",
    "cached_model",
    "part_from_model",
    "output_path",
]

#: Every artefact format, and the name its file takes beside the artwork.
#: Two rules generate this, both from the product specification: a suffix
#: names the *subject* -- ``-case`` for the enclosure, ``-assembly`` for the
#: docked result -- never the operation; and a suffix appears only where the
#: extension alone would be ambiguous, which ``.stp`` is three times over.
ARTEFACT_NAMES: dict[str, str] = {
    "excellon": "-case.drl",
    "drawing-pdf": "-case.pdf",
    "drawing-svg": "-case.svg",
    "step": "-case.stp",
    "json": "-case.json",
    "report": "-assembly.json",
    "assembly": "-assembly.stp",
}

#: Suffixes this tool writes, so a board scan never offers one back as input.
_OURS = frozenset(ARTEFACT_NAMES.values())


def panels(directory: Path) -> tuple[Path, ...]:
    """Every Illustrator file beside the working directory, in name order.

    An empty result is a state rather than a failure -- spec decision 6
    opens the workbench blocked on it -- so nothing is raised here.
    """
    return tuple(sorted(directory.glob("*.ai")))


def layers(panel: Path) -> tuple[str, ...]:
    """The artwork's own top-level layer names, in document order.

    Which layer holds the drill circles is a choice between names the file
    already carries, which is why it is a list to pick from rather than a
    string to type.
    """
    return AiPdfSource(panel).layers()


def board_candidates(
    directory: Path, panel: Path, case_model: Path | None
) -> tuple[Path, ...]:
    """Every STEP file that could be a board: not the case, not ours.

    ``-pcb`` leads because it is this project's own naming for a board and
    is therefore the likeliest answer; everything else follows by name, so
    the order never depends on how the filesystem happened to list them.
    """
    stem = panel.stem
    found = [
        path
        for path in sorted(directory.glob("*.stp"))
        if path != case_model
        and not any(path.name == f"{stem}{suffix}" for suffix in _OURS)
    ]
    return tuple(sorted(found, key=lambda path: (not path.stem.endswith("-pcb"), path.name)))


def cached_model(part: str, cache: Path) -> Discovery[Path] | None:
    """The enclosure model already cached for this part, if one is."""
    candidate = cache / f"{part}.stp"
    if not candidate.is_file():
        return None
    return Discovery(candidate, f"cached for {part}")


def part_from_model(path: Path) -> str | None:
    """The catalogue part a model's filename names, or ``None``.

    ``stompdrill`` owns this rule, and owns verifying the answer against
    the measurement. Restating either here would give one question two
    answers.
    """
    return infer_part_name(path)


def output_path(format_name: str, panel: Path) -> Path:
    """Where one artefact goes by default: beside the artwork, named from it."""
    return panel.with_name(f"{panel.stem}{ARTEFACT_NAMES[format_name]}")
