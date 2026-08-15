"""Validators — stages that inspect and report but never change the data.

Keeping validation in a stage rather than in an emitter means the drawing's
NOTES block, the JSON diagnostics and the CLI's warnings are three renderings of
one finding, not three computations of it.
"""

from __future__ import annotations

from typing import ClassVar

from ..model import Diagnostic, DrillData, StageRun
from ..tolerance import within

__all__ = ["CheckReferenceSize"]


class CheckReferenceSize:
    """Compare the reference outline against the declared true size.

    A panel drawn at 112.4 mm for a 113 mm enclosure fits nothing, and the error
    is invisible in the artwork. This is the only place that comparison is made.

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
        if data.reference is None:
            return data.with_diagnostics(
                Diagnostic.info(
                    "no-reference-outline",
                    f"no reference outline to check against the declared "
                    f"{self.expected[0]:g} × {self.expected[1]:g} mm",
                )
            )

        expected_w, expected_h = self.expected
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
            )
        )
