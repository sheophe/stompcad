"""Read PDF-compatible Illustrator artwork as raw drill geometry.

Return float millimetres, outline-centred when a reference exists; otherwise
page-relative with a diagnostic. Layers and graphics state are resolved first.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

import pikepdf

from stompmodel.diagnostics import Diagnostic
from stompmodel.model import RawHole, RawOutline, SourceInfo
from stompmodel.units import Millimetre

from ..errors import EmptyLayerError, LayerNotFoundError, SourceError
from ..geometry import (
    ClosePath,
    CurveTo,
    LineTo,
    Matrix,
    MoveTo,
    Point,
    Segment,
    SubPath,
    fit_circle,
    multiply,
    transform,
)
from ..quantise import RawDrillData
from ..units import mm_from_pt

__all__ = ["AiPdfSource"]

#: Operators that end the current path; ``n`` discharges it without painting.
_PAINT_OPS = frozenset({"S", "s", "f", "F", "f*", "B", "B*", "b", "b*", "n"})

#: Path-ending operators that mark no ink, whether or not clipping preceded them.
_NO_PAINT_OPS = frozenset({"n"})

#: How deep Form XObjects may nest before we assume a malicious or broken file.
_MAX_FORM_DEPTH = 12


@dataclass(frozen=True, slots=True)
class _LayerPath:
    """One painted subpath in page space, with the layers it was drawn inside."""

    layers: frozenset[str]
    path: SubPath


class AiPdfSource:
    """Read drill geometry from a PDF-compatible ``.ai`` file.

    ``drill_layer`` supplies circles; ``reference_layer`` supplies the outline
    for a millimetre, Y-up frame centred on that outline.
    """

    def __init__(
        self,
        path: str | Path,
        drill_layer: str = "Drill",
        reference_layer: str = "Background",
    ) -> None:
        self.path = Path(path)
        self.drill_layer = drill_layer
        self.reference_layer = reference_layer

    def __repr__(self) -> str:
        return (
            f"AiPdfSource({str(self.path)!r}, drill_layer={self.drill_layer!r}, "
            f"reference_layer={self.reference_layer!r})"
        )

    # -- public API ------------------------------------------------------

    def layers(self) -> tuple[str, ...]:
        """Every top-level Illustrator layer name, in document order."""
        return self._extract()[0]

    def layer_subpaths(self, layer: str) -> tuple[SubPath, ...]:
        """Return painted page-space subpaths on ``layer``, excluding clips."""
        names, paths = self._extract()
        self._require_layer(layer, names)
        return tuple(p.path for p in paths if layer in p.layers)

    def read(self) -> RawDrillData:
        """Return ``RawDrillData`` in the frame established by the artwork.

        Positions are outline-centred when possible, else page-relative with a
        diagnostic naming the fallback frame.
        """
        names, paths = self._extract()
        self._require_layer(self.drill_layer, names)
        self._require_layer(self.reference_layer, names)

        diagnostics: list[Diagnostic] = []

        drill_paths = [p.path for p in paths if self.drill_layer in p.layers]
        circles = [c for c in (fit_circle(p) for p in drill_paths) if c is not None]
        if not circles:
            raise _empty_layer(self.drill_layer, len(drill_paths))

        ignored = len(drill_paths) - len(circles)
        if ignored:
            diagnostics.append(
                Diagnostic.info(
                    "non-circular-path",
                    f"ignored {ignored} non-circular path(s) on layer "
                    f"{self.drill_layer!r}: only circles are drillable",
                )
            )

        reference_paths = [p.path for p in paths if self.reference_layer in p.layers]
        outline = _largest_non_circular(reference_paths)
        if outline is None:
            # Without an outline, preserve page-space coordinates and diagnose it.
            centre = (Millimetre(0.0), Millimetre(0.0))
            reference = None
            diagnostics.append(
                Diagnostic.warning(
                    # Distinct from CheckReferenceSize's INFO diagnostic code.
                    "reference-outline-not-found",
                    f"layer {self.reference_layer!r} has no non-circular path to use "
                    f"as the panel outline; hole positions are page-relative, "
                    f"measured from the MediaBox corner",
                )
            )
        else:
            x0, y0, x1, y1 = outline
            centre = (mm_from_pt((x0 + x1) / 2.0), mm_from_pt((y0 + y1) / 2.0))
            reference = RawOutline(
                width=mm_from_pt(x1 - x0),
                height=mm_from_pt(y1 - y0),
            )

        # Artwork order is not a stable identity: ADR-0006 reserves numbering
        # for RouteHoles, so no traversal position is recorded here.
        holes = tuple(
            RawHole(
                x=Millimetre(mm_from_pt(c.cx) - centre[0]),
                y=Millimetre(mm_from_pt(c.cy) - centre[1]),
                diameter=mm_from_pt(c.diameter),
            )
            for c in circles
        )

        return RawDrillData(
            holes=holes,
            reference=reference,
            centre=centre,
            diagnostics=tuple(diagnostics),
            source=SourceInfo(
                path=str(self.path),
                drill_layer=self.drill_layer,
                reference_layer=self.reference_layer,
                layers_found=names,
                producer="stompdrill",
            ),
        )

    # -- reading ---------------------------------------------------------

    def _extract(self) -> tuple[tuple[str, ...], list[_LayerPath]]:
        """Open the file once and return (layer names, painted subpaths)."""
        try:
            with pikepdf.open(self.path) as pdf:
                names = _layer_names(pdf)
                if len(pdf.pages) == 0:
                    raise SourceError(f"{self.path} has no pages")
                page = pdf.pages[0]
                return names, _walk_page(page)
        except (OSError, pikepdf.PdfError) as exc:
            raise SourceError(f"cannot read {self.path}: {exc}") from exc

    def _require_layer(self, layer: str, names: Sequence[str]) -> None:
        if layer not in names:
            raise LayerNotFoundError(layer, names)


# ---------------------------------------------------------------------------
# optional content
# ---------------------------------------------------------------------------


def _layer_names(pdf: pikepdf.Pdf) -> tuple[str, ...]:
    """Top-level layer names from ``/OCProperties`` → ``/OCGs``, in order."""
    properties = pdf.Root.get("/OCProperties")
    if properties is None:
        return ()
    names = []
    for ocg in properties.get("/OCGs", []):
        name = _ocg_name(ocg)
        if name is not None and name not in names:
            names.append(name)
    return tuple(names)


def _ocg_name(ocg) -> str | None:
    try:
        name = ocg.get("/Name")
    except AttributeError:
        return None
    return None if name is None else str(name)


def _oc_layers(operands, resources) -> frozenset[str]:
    """Resolve the layer a ``BDC /OC /MCn`` puts its content on.

    Resolve names against the current resource dictionary so Form XObjects can
    supply their own. Unresolved or non-optional content contributes no layer.
    """
    if len(operands) < 2 or str(operands[0]) != "/OC":
        return frozenset()

    target = operands[1]
    if not isinstance(target, pikepdf.Name):
        return frozenset()
    table = resources.get("/Properties") if resources is not None else None
    if table is None:
        return frozenset()
    name = _ocg_name(table.get(str(target)))
    return frozenset() if name is None else frozenset({name})


# ---------------------------------------------------------------------------
# content-stream walk
# ---------------------------------------------------------------------------


def _walk_page(page: pikepdf.Page) -> list[_LayerPath]:
    """Every painted, non-clipping subpath on the page, in page space.

    Page space is PDF points from the ``/MediaBox`` lower-left corner; the base
    CTM removes a non-zero box offset.
    """
    box = [float(v) for v in page.MediaBox]
    base: Matrix = (1.0, 0.0, 0.0, 1.0, -box[0], -box[1])
    out: list[_LayerPath] = []
    _walk(page, page.get("/Resources"), base, (), out, 0)
    return out


def _walk(
    source,
    resources,
    ctm: Matrix,
    marks: tuple[frozenset[str], ...],
    out: list[_LayerPath],
    depth: int,
) -> None:
    """Interpret one content stream, appending to ``out``.

    ``marks`` is inherited by nested forms, but each stream may close only the
    marked-content entries it opened.
    """
    stack: list[Matrix] = []
    floor = len(marks)
    builder = _PathBuilder(ctm)

    for instruction in pikepdf.parse_content_stream(source):
        op = str(instruction.operator)
        operands = instruction.operands

        # -- graphics state
        if op == "q":
            stack.append(builder.ctm)
        elif op == "Q":
            # Ignore unmatched restores at a stream's base graphics state.
            if stack:
                builder.ctm = stack.pop()
        elif op == "cm":
            values = _numbers(operands, 6)
            if values is not None:
                builder.ctm = multiply(_as_matrix(values), builder.ctm)

        # -- marked content
        elif op == "BDC":
            marks = marks + (_oc_layers(operands, resources),)
        elif op == "BMC":
            marks = marks + (frozenset(),)
        elif op == "EMC":
            if len(marks) > floor:
                marks = marks[:-1]

        # -- path construction
        elif op in ("m", "l", "c", "v", "y", "h", "re"):
            builder.construct(op, operands)
        elif op in ("W", "W*"):
            # Clipping does not decide whether the path paints; its terminator does.
            pass

        # -- path painting
        elif op in _PAINT_OPS:
            # Every painting operator ends the path, including non-painting ``n``.
            painted = builder.flush()
            if op in _NO_PAINT_OPS:
                continue
            layers = frozenset().union(*marks) if marks else frozenset()
            for path in painted:
                out.append(_LayerPath(layers=layers, path=path))

        # -- forms
        elif op == "Do" and depth < _MAX_FORM_DEPTH:
            form = _form_xobject(operands, resources)
            if form is not None:
                matrix = _numbers(form.get("/Matrix"), 6)
                inner = builder.ctm
                if matrix is not None:
                    inner = multiply(_as_matrix(matrix), inner)
                _walk(form, form.get("/Resources", resources), inner, marks, out, depth + 1)


class _PathBuilder:
    """Accumulates path-construction operators into device-space subpaths.

    Points use the CTM active when constructed, which may differ at paint time.
    """

    __slots__ = ("ctm", "_done", "_current", "_point", "_start")

    def __init__(self, ctm: Matrix) -> None:
        self.ctm: Matrix = ctm
        self._done: list[SubPath] = []
        self._current: list[Segment] = []
        self._point: Point = (0.0, 0.0)
        self._start: Point = (0.0, 0.0)

    def construct(self, op: str, operands) -> None:
        if op == "m":
            values = _numbers(operands, 2)
            if values is None:
                return
            self._begin(self._map(values[0], values[1]))
        elif op == "l":
            values = _numbers(operands, 2)
            if values is None:
                return
            self._point = self._map(values[0], values[1])
            self._current.append(LineTo(self._point))
        elif op == "c":
            values = _numbers(operands, 6)
            if values is None:
                return
            self._curve(
                self._map(values[0], values[1]),
                self._map(values[2], values[3]),
                self._map(values[4], values[5]),
            )
        elif op == "v":
            # first control point is the current point
            values = _numbers(operands, 4)
            if values is None:
                return
            self._curve(
                self._point,
                self._map(values[0], values[1]),
                self._map(values[2], values[3]),
            )
        elif op == "y":
            # second control point is the endpoint
            values = _numbers(operands, 4)
            if values is None:
                return
            end = self._map(values[2], values[3])
            self._curve(self._map(values[0], values[1]), end, end)
        elif op == "h":
            self._close()
        elif op == "re":
            values = _numbers(operands, 4)
            if values is None:
                return
            x, y, w, h = values
            self._begin(self._map(x, y))
            self._current.append(LineTo(self._map(x + w, y)))
            self._current.append(LineTo(self._map(x + w, y + h)))
            self._current.append(LineTo(self._map(x, y + h)))
            self._current.append(ClosePath())
            self._point = self._start

    def flush(self) -> list[SubPath]:
        """End the path and return its subpaths, whether or not it clips.

        The caller decides whether the terminating operator painted; ``W`` and
        ``W*`` alone do not discard geometry.
        """
        if self._current:
            self._done.append(SubPath(tuple(self._current)))
        paths = self._done
        self._done = []
        self._current = []
        return paths

    # -- internals
    def _map(self, x: float, y: float) -> Point:
        return transform(self.ctm, x, y)

    def _begin(self, point: Point) -> None:
        if self._current:
            self._done.append(SubPath(tuple(self._current)))
        self._current = [MoveTo(point)]
        self._point = point
        self._start = point

    def _curve(self, c1: Point, c2: Point, end: Point) -> None:
        self._current.append(CurveTo(c1=c1, c2=c2, end=end))
        self._point = end

    def _close(self) -> None:
        if self._current:
            self._current.append(ClosePath())
            self._point = self._start


def _form_xobject(operands, resources):
    """The Form XObject a ``Do`` names, or ``None`` if it is an image or absent."""
    if not operands or resources is None:
        return None
    table = resources.get("/XObject")
    if table is None:
        return None
    form = table.get(str(operands[0]))
    if form is None:
        return None
    try:
        if str(form.get("/Subtype")) != "/Form":
            return None
    except AttributeError:
        return None
    return form


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------


def _numbers(operands, count: int) -> list[float] | None:
    """``count`` floats from ``operands``, or ``None`` if it isn't that shape.

    Malformed operators are skipped without aborting the remaining stream.
    """
    if operands is None or len(operands) != count:
        return None
    try:
        return [float(v) for v in operands]
    except (TypeError, ValueError):
        return None


def _empty_layer(layer: str, path_count: int) -> EmptyLayerError:
    """The right ``EmptyLayerError`` for why ``layer`` yielded no circle.

    Zero paths means no painted artwork reached the stream; a positive count
    means every path failed the circle predicate.
    """
    error = EmptyLayerError(layer)
    if path_count:
        error.args = (
            (
                f"layer {layer!r} has {path_count} path(s) but none of them is a circle. "
                "Only true circles are drillable: four cubic Beziers, equal radii, "
                "kappa-consistent controls. Rounded rectangles, ellipses, compound "
                "shapes and stray marks all read as non-circular here."
            ),
        )
    return error


def _as_matrix(values: Sequence[float]) -> Matrix:
    a, b, c, d, e, f = values
    return (a, b, c, d, e, f)


def _largest_non_circular(
    paths: Iterable[SubPath],
) -> tuple[float, float, float, float] | None:
    """Return the largest-area non-circular path's bounds, or ``None``.

    Circles cannot define the panel; area prevents a long thin path from winning.
    """
    best: tuple[float, float, float, float] | None = None
    best_area = 0.0
    for path in paths:
        if fit_circle(path) is not None:
            continue
        # every emitted subpath begins with a MoveTo, so bbox always has anchors
        x0, y0, x1, y1 = path.bbox
        area = (x1 - x0) * (y1 - y0)
        if area > best_area:
            best_area = area
            best = (x0, y0, x1, y1)
    return best
