"""Shared test helpers.

Four helpers lived in more than one test module, and two of them had already
drifted. ``clean_registry`` existed twice and the copies disagreed about what
they yield — one handed the test ``base.REGISTRY``, the other nothing — so a
test moved between files could stop compiling. ``make_data`` existed twice and
the copies disagreed about ``SourceInfo``, which means the two files were not
testing quite the same object. (``at`` was the one pair still byte-identical,
which is how divergence starts, not evidence against it.) One definition each,
here, so the next change lands in one place.

``circle_ops`` and ``build_pdf`` are here for the same reason and no other. They
began as ``test_ai_pdf.py``'s private helpers, where every user was a source
test; the quantisation phase then needed artwork too, because a diagnostic about
what a designer *meant* cannot be proved against a hand-built measurement that
never went through the float arithmetic a real page puts a circle through. One
definition, rather than a second synthetic-PDF builder free to disagree with
this one about what a layer is.
"""

from __future__ import annotations

from pathlib import Path

import pikepdf
import pytest
from pikepdf import Array, Dictionary, Name, String

from aidrill.emitters import base
from aidrill.geometry import KAPPA
from aidrill.model import DrillData, Hole, ReferenceOutline, SourceInfo

__all__ = [
    "at",
    "clean_registry",
    "codes",
    "diameters",
    "holes",
    "make_data",
    "positions",
    "circle_ops",
    "build_pdf",
]


@pytest.fixture
def clean_registry():
    """Snapshot and restore the emitter registry around a test.

    Registering is a global side effect, and a test that leaked one would change
    what every later test — and ``--help`` — sees.
    """
    saved = dict(base.REGISTRY)
    try:
        yield base.REGISTRY
    finally:
        base.REGISTRY.clear()
        base.REGISTRY.update(saved)


def at(x_nm: int, y_nm: int, diameter_nm: int = 7_000_000, *, index: int) -> Hole:
    """One quantised hole with an explicit identity.

    Nanometres, because that is the only unit a ``Hole`` holds: these helpers
    build the *output* side of the quantisation phase, never its input. A test
    that needs a measurement builds a ``RawHole`` itself, in millimetres, near
    the assertion that cares about it.

    ``index`` is keyword-only so a test can never pass it by accident where
    ``diameter_nm`` was meant.
    """
    return Hole.from_measurement(x_nm, y_nm, diameter_nm, index=index)


def holes(*specs: tuple[int, ...]) -> tuple[Hole, ...]:
    """Build holes from ``(x_nm, y_nm[, diameter_nm])`` triples, numbering them 0..n-1.

    Sequential numbering here is deterministic per call — no module-level
    counter, so a test's hole ids do not depend on which tests ran before it.

    It also makes ``index`` indistinguishable from array position, which is the
    coincidence this repo has been bitten by: an assertion about identity passes
    for position too. That is fine for the many tests that never mention an
    index, and wrong for any test that does — those must use ``at`` with
    deliberately out-of-order numbers instead of this.
    """
    return tuple(
        Hole.from_measurement(s[0], s[1], s[2] if len(s) > 2 else 7_000_000, index=i)
        for i, s in enumerate(specs)
    )


def make_data(*given: Hole, reference: ReferenceOutline | None = None) -> DrillData:
    """A ``DrillData`` around some holes, with provenance filled in.

    The two copies of this had diverged only in their ``SourceInfo``, and no
    test asserted on either version's, so the richer one wins.
    """
    return DrillData(
        holes=tuple(given),
        reference=reference,
        diagnostics=(),
        source=SourceInfo(path="panel.ai", drill_layer="Drill"),
    )


def codes(data: DrillData) -> list[str]:
    """The stable machine key of every diagnostic a stage raised, in order.

    Every diagnostic assertion in the pipeline tests matches on ``code``, never
    on ``message`` -- ``code`` is the stable API and the wording is not -- and
    this is what every one of those assertions goes through.
    """
    return [d.code for d in data.diagnostics]


def positions(data: DrillData) -> list[tuple[int, int]]:
    return [(h.x_nm, h.y_nm) for h in data.holes]


def diameters(data: DrillData) -> list[int]:
    return [h.diameter_nm for h in data.holes]


def circle_ops(cx: float, cy: float, r: float, paint: str = "S") -> str:
    """Content-stream ops drawing a circle the way every vector tool does."""
    k = KAPPA * r
    return (
        f"{cx + r} {cy} m "
        f"{cx + r} {cy + k} {cx + k} {cy + r} {cx} {cy + r} c "
        f"{cx - k} {cy + r} {cx - r} {cy + k} {cx - r} {cy} c "
        f"{cx - r} {cy - k} {cx - k} {cy - r} {cx} {cy - r} c "
        f"{cx + k} {cy - r} {cx + r} {cy - k} {cx + r} {cy} c h {paint}"
    )


def build_pdf(
    path: Path,
    layers: dict[str, str],
    *,
    media: tuple[float, float, float, float] = (0, 0, 400, 400),
    form: tuple[list[float], str] | None = None,
    form_properties: dict[str, str] | None = None,
    image: bool = False,
    extra: str = "",
) -> Path:
    """Write a one-page PDF whose layers are OCGs, like a native ``.ai`` save.

    ``layers`` maps a layer name to the content stream drawn inside its marked
    content. ``form`` optionally installs ``/Fm0`` as a Form XObject with the
    given ``/Matrix`` and content; ``image`` installs ``/Im0``, a placed image.

    A form gets **no** ``/Resources`` of its own unless ``form_properties`` asks
    for one, which maps ``/MCn`` tokens onto the OCGs of the named layers. The
    two cases must stay distinguishable: giving every form the page's own table
    would make the fallback and the real lookup produce the same answer, and no
    fixture could then tell whether a form's resources were consulted at all.
    """
    pdf = pikepdf.new()
    ocgs = []
    properties = Dictionary()
    ocg_of: dict[str, object] = {}
    body = []
    for index, (name, content) in enumerate(layers.items()):
        ocg = pdf.make_indirect(Dictionary(Type=Name.OCG, Name=String(name)))
        ocgs.append(ocg)
        ocg_of[name] = ocg
        properties[f"/MC{index}"] = ocg
        body.append(f"/OC /MC{index} BDC {content} EMC")
    pdf.Root.OCProperties = pdf.make_indirect(
        Dictionary(OCGs=Array(ocgs), D=Dictionary(Order=Array(ocgs), ON=Array(ocgs)))
    )

    resources = Dictionary(Properties=properties)
    if form is not None:
        matrix, form_content = form
        stream = pdf.make_stream(form_content.encode())
        stream.Type = Name.XObject
        stream.Subtype = Name.Form
        stream.BBox = Array([0, 0, 10000, 10000])
        stream.Matrix = Array(list(matrix))
        if form_properties is not None:
            own = Dictionary()
            for token, layer in form_properties.items():
                own[token] = ocg_of[layer]
            stream.Resources = Dictionary(Properties=own)
        resources.XObject = Dictionary(Fm0=pdf.make_indirect(stream))
    if image:
        picture = pdf.make_stream(b"\xff\x00\x00")
        picture.Type = Name.XObject
        picture.Subtype = Name.Image
        picture.Width = 1
        picture.Height = 1
        picture.ColorSpace = Name.DeviceRGB
        picture.BitsPerComponent = 8
        table = resources.get("/XObject") or Dictionary()
        table.Im0 = pdf.make_indirect(picture)
        resources.XObject = table

    page = pikepdf.Page(
        pdf.make_indirect(
            Dictionary(
                Type=Name.Page,
                MediaBox=Array(list(media)),
                Resources=resources,
                Contents=pdf.make_indirect(pdf.make_stream(("\n".join(body) + extra).encode())),
            )
        )
    )
    pdf.pages.append(page)
    pdf.save(path)
    return path
