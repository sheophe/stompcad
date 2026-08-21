"""What a recovery reports, in canonical units, whatever format it read.

Named fields rather than positions: transposing x and y is the characteristic
bug in a helper like this, and a positional tuple hides it. Every field is
what the artefact *states*, never what the model holds -- the comparison is
the test's job, not the vocabulary's.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from stompmodel.units import Nanometre

__all__ = ["NM_PER_MM", "RecoveredCircle", "RecoveredPanel", "nm_from_decimal"]

#: Nanometres in a millimetre. Stated here so a recovery never spells 1e6.
NM_PER_MM = 1_000_000


@dataclass(frozen=True, slots=True)
class RecoveredCircle:
    """One circle an artefact states, hole or furniture.

    ``number``, ``tool`` and ``cls`` are the claims only some formats carry:
    Excellon states a tool and a sequence and no class, SVG states a class
    and neither of the others, and PDF states none of the three.
    """

    x_nm: Nanometre
    y_nm: Nanometre
    diameter_nm: Nanometre
    number: int | None = None
    tool: int | None = None
    cls: str = ""


@dataclass(frozen=True, slots=True)
class RecoveredPanel:
    """Everything one artefact states about one panel.

    ``comments`` is the header prose only Excellon carries and ``outline_nm``
    the extent only the drawings do; each is empty or ``None`` where its
    format states nothing, so a comparison cannot check a field by accident.
    """

    circles: tuple[RecoveredCircle, ...] = ()
    outline_nm: tuple[Nanometre, Nanometre] | None = None
    comments: tuple[str, ...] = ()


def nm_from_decimal(token: str | Decimal) -> Nanometre:
    """Exact nanometres from a decimal value, refusing a finer one.

    ``Decimal`` rather than ``float`` so the comparison can demand equality
    instead of an epsilon; a token past six decimals states a length the
    canonical model cannot hold, and is a defect in the writer, not a
    rounding question for the reader.
    """
    scaled = Decimal(token) * NM_PER_MM
    if scaled != scaled.to_integral_value():
        raise ValueError(f"not a whole number of nanometres: {token!r}")
    return Nanometre(int(scaled))
