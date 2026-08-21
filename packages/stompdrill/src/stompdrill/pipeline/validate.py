"""Validation stages that report findings without changing any data.

``CheckOutlineContainment`` is in the CLI pipeline. ``CheckReferenceSize`` is
not: ``--case`` owns catalogue identity there, and a library caller may compose
that independent size assertion.
"""

from __future__ import annotations

from typing import ClassVar

from stompmodel.diagnostics import Diagnostic
from stompmodel.model import DrillData, Hole, ReferenceOutline, StageRun
from stompmodel.units import Nanometre, format_nm

from ..tolerance import within

__all__ = ["CheckOutlineContainment", "CheckReferenceSize"]


class CheckReferenceSize:
    """Compare a reference outline with a declared whole-nanometre size.

    A missing outline yields ``no-reference-outline`` INFO; a difference beyond
    the inclusive per-axis tolerance yields ``reference-size-mismatch`` WARNING.
    """

    name: ClassVar[str] = "check-reference-size"

    def __init__(
        self,
        expected_nm: tuple[Nanometre, Nanometre],
        tolerance_nm: Nanometre = Nanometre(50_000),
    ) -> None:
        self.expected_nm = (
            _whole_nanometres("expected width", expected_nm[0]),
            _whole_nanometres("expected height", expected_nm[1]),
        )
        self.tolerance_nm = _whole_nanometres("tolerance", tolerance_nm)

    def describe(self) -> StageRun:
        """Record expected width, expected height and tolerance as scalars."""
        return StageRun(
            self.name,
            (
                ("expected_width_nm", self.expected_nm[0]),
                ("expected_height_nm", self.expected_nm[1]),
                ("tolerance_nm", self.tolerance_nm),
            ),
        )

    def apply(self, data: DrillData) -> DrillData:
        expected_w, expected_h = self.expected_nm
        if data.reference is None:
            return data.with_diagnostics(
                Diagnostic.info(
                    "no-reference-outline",
                    f"no reference outline to check against the declared "
                    f"{format_nm(expected_w)} × {format_nm(expected_h)} mm",
                    data=(
                        ("expected_width_nm", expected_w),
                        ("expected_height_nm", expected_h),
                        ("tolerance_nm", self.tolerance_nm),
                    ),
                )
            )

        dw = Nanometre(data.reference.width_nm - expected_w)
        dh = Nanometre(data.reference.height_nm - expected_h)
        # ``within``, not a bare ``<=``: the boundary is one decision and it is
        # owned there. A caller who declares a 50 000 nm slack on a panel that
        # is 50 000 nm out typed the number they meant.
        if within(data.reference.width_nm, expected_w, self.tolerance_nm) and within(
            data.reference.height_nm, expected_h, self.tolerance_nm
        ):
            return data

        # The per-side figures floor rather than introducing the first float
        # into the model, exactly as ``DrillData.with_origin`` does: an odd
        # number of nanometres has no exact half, and half a nanometre is three
        # decimal places below anything any artifact prints.
        return data.with_diagnostics(
            Diagnostic.warning(
                "reference-size-mismatch",
                f"reference outline is {format_nm(data.reference.width_nm)} × "
                f"{format_nm(data.reference.height_nm)} mm, declared "
                f"{format_nm(expected_w)} × {format_nm(expected_h)} mm: "
                f"total {_signed_mm(dw)} × {_signed_mm(dh)} mm, "
                f"per side {_signed_mm(Nanometre(dw // 2))} × "
                f"{_signed_mm(Nanometre(dh // 2))} mm",
                # The differences travel with the finding rather than only
                # inside the sentence: they are the arithmetic this stage exists
                # to do, and a consumer that had to parse them back out of the
                # prose — or subtract the two sizes again — would be the second
                # place in the program computing them.
                data=(
                    ("width_nm", data.reference.width_nm),
                    ("height_nm", data.reference.height_nm),
                    ("expected_width_nm", expected_w),
                    ("expected_height_nm", expected_h),
                    ("delta_width_nm", dw),
                    ("delta_height_nm", dh),
                    ("tolerance_nm", self.tolerance_nm),
                ),
            )
        )


class CheckOutlineContainment:
    """Warn about a hole whose extent leaves the reference outline.

    The extent, not the centre, so an edge breakout is caught. A warning rather
    than an error because the outline is a published top view and not the
    drilled face: see ADR-0002. A panel with no outline has no boundary to
    leave and is skipped.
    """

    name: ClassVar[str] = "check-outline-containment"

    def describe(self) -> StageRun:
        """Record that parameter-free containment ran."""
        return StageRun(self.name, ())

    def apply(self, data: DrillData) -> DrillData:
        outline = data.reference
        if outline is None:
            return data
        findings = []
        for hole in data.holes:
            # Doubled, so the decision needs no halving. A hole centred at ``x``
            # spans ``2|x| + d`` across that axis, and comparing that with the
            # full dimension keeps the boundary exact -- rounding a half-nanometre
            # radius here would settle a boundary case by arithmetic nobody wrote.
            over_x = 2 * abs(hole.x_nm) + hole.diameter_nm - outline.width_nm
            over_y = 2 * abs(hole.y_nm) + hole.diameter_nm - outline.height_nm
            if over_x > 0 or over_y > 0:
                findings.append(_outside(hole, outline, over_x, over_y))
        return data.with_diagnostics(*findings)


def _whole_nanometres(name: str, value: Nanometre) -> Nanometre:
    """Require a plain ``int`` nanometre length, excluding floats and booleans."""
    if type(value) is not int:
        raise TypeError(f"{name} must be a whole number of nanometres, not {value!r}")
    return value


def _signed_mm(nm: Nanometre) -> str:
    """Format a nanometre difference in millimetres with an explicit sign."""
    text = format_nm(nm)
    return text if text.startswith("-") else f"+{text}"


def _outside(
    hole: Hole, outline: ReferenceOutline, over_x: int, over_y: int
) -> Diagnostic:
    """Report a breakout, with each axis's own overshoot on the finding.

    The sentence states the worst overshoot and the payload states both, so a
    consumer never has to subtract the two sizes back out of the prose.
    """
    x_nm = _overshoot(over_x)
    y_nm = _overshoot(over_y)
    return Diagnostic.warning(
        "hole-outside-outline",
        f"⌀{format_nm(hole.diameter_nm)} mm hole at "
        f"({format_nm(hole.x_nm)}, {format_nm(hole.y_nm)}) reaches "
        f"{format_nm(Nanometre(max(x_nm, y_nm)))} mm past the "
        f"{format_nm(outline.width_nm)} × {format_nm(outline.height_nm)} mm outline",
        location_nm=(hole.x_nm, hole.y_nm),
        data=(
            ("diameter_nm", hole.diameter_nm),
            ("overshoot_x_nm", x_nm),
            ("overshoot_y_nm", y_nm),
            ("width_nm", outline.width_nm),
            ("height_nm", outline.height_nm),
        ),
    )


def _overshoot(doubled_nm: int) -> Nanometre:
    """Halve a doubled overshoot, rounding up; a contained axis reports nought.

    Ceiling for the reason ``CheckCaseClearance`` ceilings its radius: the
    breakout reported must never read smaller than the metal actually lost.
    """
    return Nanometre(0 if doubled_nm <= 0 else -(-doubled_nm // 2))
