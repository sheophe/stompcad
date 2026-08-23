"""Shared fixtures and builders for quantised data and synthetic Illustrator PDFs."""

from __future__ import annotations

from pathlib import Path

import pikepdf
import pytest
from pikepdf import Array, Dictionary, Name, String

from stompdrill.cad import Rejection
from stompdrill.emitters import base
from stompdrill.geometry import KAPPA
from stompmodel.frames import CoordinateFrame, FaceFrame
from stompmodel.model import DrillData, Hole, ReferenceOutline, SourceInfo
from stompmodel.units import Nanometre
from tests.hammond import hammond_a, hammond_b, hammond_bb, hammond_y  # noqa: F401  (pytest fixtures)

__all__ = [
    "at",
    "clean_registry",
    "codes",
    "diameters",
    "holes",
    "make_data",
    "positions",
    "circle_ops",
    "self_nesting_form",
    "image_ending_form",
    "build_pdf",
    "FakeCase",
]

_MM = 1_000_000


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


def at(x_nm: int, y_nm: int, diameter_nm: int = 7_000_000, *, index: int | None = None) -> Hole:
    """One quantised hole, numbered as if RouteHoles had already run.

    Plain integers are branded here so a test may write the literal it means;
    this helper is the suite's nanometre boundary.
    """
    hole = Hole.from_measurement(Nanometre(x_nm), Nanometre(y_nm), Nanometre(diameter_nm))
    return hole if index is None else hole.with_number(index)


def holes(*specs: tuple[int, ...]) -> tuple[Hole, ...]:
    """Build and sequentially number holes from coordinate triples, from 1.

    A test proving an emitter reads the number through ``DrillData.numbered()``
    rather than list position should use ``at`` instead, whose number can be
    given out of tuple order.
    """
    return tuple(
        Hole.from_measurement(
            Nanometre(s[0]),
            Nanometre(s[1]),
            Nanometre(s[2] if len(s) > 2 else 7_000_000),
        ).with_number(i)
        for i, s in enumerate(specs, start=1)
    )


def make_data(*given: Hole, reference: ReferenceOutline | None = None) -> DrillData:
    """Build ``DrillData`` with fixed source provenance."""
    return DrillData(
        holes=tuple(given),
        reference=reference,
        diagnostics=(),
        source=SourceInfo(path="panel.ai", drill_layer="Drill"),
    )


def codes(data: DrillData) -> list[str]:
    """The stable machine key of every diagnostic a stage raised, in order."""
    return [d.code for d in data.diagnostics]


def positions(data: DrillData) -> list[tuple[Nanometre, Nanometre]]:
    return [(h.x_nm, h.y_nm) for h in data.holes]


def diameters(data: DrillData) -> list[Nanometre]:
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


def self_nesting_form(cx: float = 20.0, cy: float = 20.0, r: float = 5.0) -> str:
    """A form body that draws a circle and then invokes itself.

    ``build_pdf`` gives the form no ``/Resources``, so ``/Fm0`` resolves against
    the page's and the form re-enters itself. Recursion ends only at the reader's
    depth limit, which is what makes this the vehicle for testing that limit.
    """
    return f"{circle_ops(cx, cy, r)} /Fm0 Do"


def image_ending_form(cx: float = 20.0, cy: float = 20.0, r: float = 5.0) -> str:
    """A form body ending in a ``Do`` that names an image, not another form."""
    return f"{circle_ops(cx, cy, r)} /Im0 Do"


def build_pdf(
    path: Path,
    layers: dict[str, str],
    *,
    media: tuple[float, float, float, float] = (0, 0, 400, 400),
    form: tuple[list[float], str] | None = None,
    form_bbox: tuple[float, float, float, float] = (0, 0, 10000, 10000),
    form_properties: dict[str, str] | None = None,
    image: bool = False,
    extra: str = "",
) -> Path:
    """Write a one-page PDF whose layers are OCGs, like a native ``.ai`` save.

    Forms only receive resources when requested, keeping lookup and fallback distinct.
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
        stream.BBox = Array(list(form_bbox))
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


class FakeCase:
    """A rectangular play area with optional boss discs and a lid overlay.

    Distances are nanometres. ``bosses`` reject as THROUGH_BOSS, ``behind`` as
    OBSTRUCTED, so a test can aim at exactly one code.
    """

    part = "1590BB"
    face = "box"
    model_name = "1590BB.stp"
    footprint_nm = (Nanometre(119_500_000), Nanometre(94_000_000))
    plate_nm = Nanometre(2_250_000)
    frame = FaceFrame(
        basis=CoordinateFrame(
            origin_nm=(Nanometre(0), Nanometre(0), Nanometre(-30 * _MM)),
            u=(1.0, 0.0, 0.0), v=(0.0, -1.0, 0.0), w=(0.0, 0.0, -1.0),
        )
    )

    def __init__(
        self, half_x=50 * _MM, half_y=40 * _MM, bosses=(), behind=(), margin_nm=1_000_000
    ):
        self.play_area_nm = (
            Nanometre(-half_x), Nanometre(-half_y), Nanometre(half_x), Nanometre(half_y)
        )
        self.bosses = bosses
        self.behind = behind
        self.margin_nm = Nanometre(margin_nm)

    def classify(self, x_nm, y_nm, radius_nm):
        x0, y0, x1, y1 = self.play_area_nm
        for cx, cy, r in self.bosses:
            if (x_nm - cx) ** 2 + (y_nm - cy) ** 2 < (r + radius_nm) ** 2:
                return Rejection.THROUGH_BOSS
        for cx, cy, r in self.behind:
            if (x_nm - cx) ** 2 + (y_nm - cy) ** 2 < (r + radius_nm) ** 2:
                return Rejection.OBSTRUCTED
        if not (x0 <= x_nm - radius_nm and x_nm + radius_nm <= x1):
            return Rejection.OFF_FACE
        if not (y0 <= y_nm - radius_nm and y_nm + radius_nm <= y1):
            return Rejection.OFF_FACE
        return None


def pytest_addoption(parser) -> None:
    """Add --hammond, which enables tests needing a downloaded Hammond model."""
    parser.addoption(
        "--hammond",
        action="store_true",
        default=False,
        help="run tests that need a real Hammond STEP model (downloads and caches it)",
    )


def pytest_configure(config) -> None:
    config.addinivalue_line(
        "markers", "hammond: needs a real Hammond model; run with --hammond"
    )


def pytest_collection_modifyitems(config, items) -> None:
    """Skip hammond-marked tests unless --hammond was given.

    Deliberately not an ``addopts`` deselection: CLAUDE.md's documented full-suite
    command passes ``-o addopts=``, which would blank it and silently re-enable
    every one of these.
    """
    if config.getoption("--hammond"):
        return
    skip = pytest.mark.skip(reason="needs a real Hammond model; run: pytest --hammond")
    for item in items:
        if "hammond" in item.keywords:
            item.add_marker(skip)
