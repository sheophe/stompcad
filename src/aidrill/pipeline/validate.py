"""Validators — stages that inspect and report but never change the data.

Keeping validation in a stage rather than in an emitter means the drawing's
NOTES block, the JSON diagnostics and the CLI's warnings are three renderings of
one finding, not three computations of it.

**Nothing here is composed by ``cli.build_pipeline``, and that is a decision
rather than an omission.** The command line's size assertion is ``--case``,
which does strictly more than a typed-out ``WxH`` — it snaps the outline to the
catalogue's whole millimetres as well as checking it, and only a *catalogue*
footprint can be snapped to. Giving the CLI this stage as well would hand it two
ways to state the panel's size with nothing to reconcile them when they
disagreed: ``--case 1590B`` beside a declared 113 × 60 has no defensible answer,
and a tool that lets an operator declare one panel twice will eventually be
handed two panels.

The caller this stage exists for is the one no command-line flag could serve: a
**library** consumer whose authority is outside this catalogue. A builder
working in a folded-aluminium box, a 3-D printed shell or any of the enclosures
the world has that Hammond does not can never reach a footprint match — the best
``IdentifyHammondFootprint`` can say about their panel is ``unknown-enclosure``,
a WARNING about *our* catalogue — and they are precisely the person who does
know, to a tenth of a millimetre, what their panel must measure. This stage is
the one way to assert it. So it stays exported, and the CLI stays out of it.

That authority is also why the mismatch is a WARNING while a contradicted
``--case`` is an ERROR. ``--case`` is an identity claim against a catalogue the
pipeline then *acts on*; this is a size comparison against a number the caller
supplied, at a tolerance the caller chose, and the caller — a program, not an
operator staring at a terminal — is the one entitled to decide what 0.4 mm is
worth on their panel. The diagnostic carries everything that decision needs.
"""

from __future__ import annotations

from typing import ClassVar

from ..model import Diagnostic, DrillData, StageRun
from ..tolerance import within

__all__ = ["CheckReferenceSize"]


class CheckReferenceSize:
    """Compare the reference outline against a size the caller declares.

    A panel drawn at 112.4 mm for a 113 mm enclosure fits nothing, and the error
    is invisible in the artwork. This is the only place that comparison is made.

    **Library-only: no CLI flag builds this, by design** — see the module
    docstring for which caller it is for and why ``--case`` does not make it
    redundant. Compose it yourself, in whatever position you like; like every
    stage it may not ask what ran before it.

    A missing reference outline is not an error here — the source may simply not
    have had a reference layer — so it reports ``no-reference-outline`` at INFO
    and returns the data untouched.
    """

    name: ClassVar[str] = "check-reference-size"

    def __init__(self, expected: tuple[float, float], tolerance: float = 0.05) -> None:
        self.expected = (float(expected[0]), float(expected[1]))
        self.tolerance = float(tolerance)

    def describe(self) -> StageRun:
        """The size the panel was declared to be, and the slack allowed on it.

        Split into width and height rather than one pair, because a parameter
        value is a scalar a consumer can print without unpacking a structure it
        would have to know the shape of.
        """
        return StageRun(
            self.name,
            (
                ("expected_width_mm", self.expected[0]),
                ("expected_height_mm", self.expected[1]),
                ("tolerance_mm", self.tolerance),
            ),
        )

    def apply(self, data: DrillData) -> DrillData:
        expected_w, expected_h = self.expected
        if data.reference is None:
            return data.with_diagnostics(
                Diagnostic.info(
                    "no-reference-outline",
                    f"no reference outline to check against the declared "
                    f"{expected_w:g} × {expected_h:g} mm",
                    data=(
                        ("expected_width_mm", expected_w),
                        ("expected_height_mm", expected_h),
                        ("tolerance_mm", self.tolerance),
                    ),
                )
            )

        dw = data.reference.width - expected_w
        dh = data.reference.height - expected_h
        # ``within``, not a bare ``<=``: 60.1 - 60.0 is 0.10000000000000142, so a
        # 0.1 tolerance the user typed exactly must still be a match.
        if within(data.reference.width, expected_w, self.tolerance) and within(
            data.reference.height, expected_h, self.tolerance
        ):
            return data

        return data.with_diagnostics(
            Diagnostic.warning(
                "reference-size-mismatch",
                f"reference outline is {data.reference.width:.3f} × "
                f"{data.reference.height:.3f} mm, declared {expected_w:g} × "
                f"{expected_h:g} mm: total {dw:+.3f} × {dh:+.3f} mm, "
                f"per side {dw / 2:+.3f} × {dh / 2:+.3f} mm",
                # The differences travel with the finding rather than only
                # inside the sentence: they are the arithmetic this stage exists
                # to do, and a consumer that had to parse them back out of the
                # prose — or subtract the two sizes again — would be the second
                # place in the program computing them.
                data=(
                    ("width_mm", data.reference.width),
                    ("height_mm", data.reference.height),
                    ("expected_width_mm", expected_w),
                    ("expected_height_mm", expected_h),
                    ("delta_width_mm", dw),
                    ("delta_height_mm", dh),
                    ("tolerance_mm", self.tolerance),
                ),
            )
        )
