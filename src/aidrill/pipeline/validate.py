"""Validators — stages that inspect and report but never change the data.

Keeping validation in a stage rather than in an emitter means the drawing's
NOTES block, the JSON diagnostics and the CLI's warnings are three renderings of
one finding, not three computations of it.

**Nothing here is composed by ``cli.build_pipeline``, and that is a decision
rather than an omission.** The command line's size assertion is ``--case``,
which does strictly more than a typed-out ``WxH`` — it puts the outline onto the
catalogue's whole millimetres as well as checking it, and only a *catalogue*
footprint can be quantised onto. Giving the CLI this stage as well would hand it
two ways to state the panel's size with nothing to reconcile them when they
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
from ..units import format_nm

__all__ = ["CheckReferenceSize"]


class CheckReferenceSize:
    """Compare the reference outline against a size the caller declares.

    A panel drawn at 112.4 mm for a 113 mm enclosure fits nothing, and the error
    is invisible in the artwork. This is the only place that comparison is made.

    Both the declared size and the slack are whole nanometres, like every other
    nominal length in the model: the outline this compares against has already
    been quantised, so a caller who states their panel in millimetres converts
    once, at their own boundary, rather than leaving this stage to do it a
    second time and differently.

    **Library-only: no CLI flag builds this, by design** — see the module
    docstring for which caller it is for and why ``--case`` does not make it
    redundant. Compose it yourself, in whatever position you like; like every
    stage it may not ask what ran before it.

    A missing reference outline is not an error here — the source may simply not
    have had a reference layer — so it reports ``no-reference-outline`` at INFO
    and returns the data untouched.
    """

    name: ClassVar[str] = "check-reference-size"

    def __init__(self, expected_nm: tuple[int, int], tolerance_nm: int = 50_000) -> None:
        self.expected_nm = (
            _whole_nanometres("expected width", expected_nm[0]),
            _whole_nanometres("expected height", expected_nm[1]),
        )
        self.tolerance_nm = _whole_nanometres("tolerance", tolerance_nm)

    def describe(self) -> StageRun:
        """The size the panel was declared to be, and the slack allowed on it.

        Split into width and height rather than one pair, because a parameter
        value is a scalar a consumer can print without unpacking a structure it
        would have to know the shape of.
        """
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

        dw = data.reference.width_nm - expected_w
        dh = data.reference.height_nm - expected_h
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
                f"per side {_signed_mm(dw // 2)} × {_signed_mm(dh // 2)} mm",
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


def _whole_nanometres(name: str, value: int) -> int:
    """A declared length that is a length. Checked once, at construction.

    The precedent ``DrillStandard.__post_init__`` sets, and for its reason: the
    alternative is noticing at every use, or not noticing at all. A caller who
    hands this stage the millimetres they were thinking in gets a comparison
    that is a million times too tight, on every panel, and the only sign of it
    is that every panel now mismatches.

    ``type(value) is not int`` and not ``isinstance``, because ``bool`` is a
    subclass of ``int``: a ``True`` tolerance is a one-nanometre tolerance, and
    a ``True`` width is a panel one nanometre across.
    """
    if type(value) is not int:
        raise TypeError(f"{name} must be a whole number of nanometres, not {value!r}")
    return value


def _signed_mm(nm: int) -> str:
    """A nanometre difference in millimetres, with the sign always shown.

    The sheet this reaches puts the two axes in a column, where a leading ``+``
    is the difference between reading a number and counting its characters.
    ``format_nm`` supplies the ``-`` and normalises negative zero away, so the
    only thing left to add is the ``+``.
    """
    text = format_nm(nm)
    return text if text.startswith("-") else f"+{text}"
