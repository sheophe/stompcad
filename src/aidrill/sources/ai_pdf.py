"""Read drill geometry out of a native Adobe Illustrator save.

A ``.ai`` file written with "Create PDF Compatible File" on — the default — is a
valid PDF, so no Illustrator, no scripting bridge and no export step is needed:
``pikepdf`` opens the artwork the designer actually saved.

What this module does is deliberately narrow (SPEC 2.1). It walks the page's
content stream, resolves the graphics state, recovers circles, and states them
in millimetres relative to the reference outline. It measures and rounds
nothing: what comes out is a ``RawDrillData``, and every length in it is the
float the artwork drew. Quantising is the next phase's business, because only
it knows the answer set a length has to land on — a drill size, a grid pitch, a
catalogue footprint — and a source that rounded first would put two roundings
in series and make their order matter.

It does **not** snap, dedupe, cluster diameters or validate anything either —
those are pipeline stages, and doing them here is precisely the layering
mistake this rewrite exists to undo. Eight circles drawn is eight holes
reported, even when two of them coincide: only the pipeline may decide that two
marks are one hole, and only it can report having done so.

The awkward parts of the format, all verified against a real Illustrator 30.7
file:

* **Layers are optional content.** ``/OCProperties`` → ``/OCGs`` gives the names;
  the page's ``/Resources`` → ``/Properties`` maps ``/MCn`` tokens onto those
  same objects, and ``BDC /OC /MCn`` in the stream is what puts a path on a
  layer. Sublayers fold into their parent OCG and are unrecoverable, as are
  Illustrator's object names — a ``.ai`` file carries no structure tree.
* **Clip paths are not geometry, and neither is anything else ``n`` ends.**
  Illustrator brackets nearly every group with an artboard-sized ``re W n``.
  Treated as a path, that rectangle would become the largest thing on the layer
  and hijack the reference outline. ``W`` is not what makes it invisible,
  though — ``n`` is; a bare ``re n`` marks no ink either and is discarded on the
  same grounds.
* **The artboard is not the enclosure.** The fixture's panel is 113 × 60 mm on
  an A4 sheet. The frame therefore comes from the reference layer's largest
  non-circular path, never from ``/MediaBox`` (SPEC 6.6).
* **A path with neither fill nor stroke is absent from the stream entirely.**
  That is the most common reason a drill layer comes back empty, so
  ``EmptyLayerError`` says so — but only when the layer really did arrive with
  no paths at all. A layer full of stroked rectangles is empty for the opposite
  reason, and telling that operator to add a stroke sends them to check the one
  thing that is already right.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

import pikepdf

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
from ..model import Diagnostic, RawDrillData, RawHole, RawOutline, SourceInfo
from ..units import mm_from_pt

__all__ = ["AiPdfSource"]

#: Operators that end the current path. ``n`` is one of them: it paints nothing
#: but still discharges the path — it is how a clip-only path is disposed of.
_PAINT_OPS = frozenset({"S", "s", "f", "F", "f*", "B", "B*", "b", "b*", "n"})

#: Of those, the ones that mark no ink. A path ended by ``n`` is invisible in
#: every viewer whether or not a ``W`` preceded it, so it is not artwork and
#: must never reach the output — an unpainted artboard-sized rectangle would
#: otherwise out-area the panel and hijack the reference frame (SPEC 6.3, 6.6).
#:
#: ``s``, ``b`` and ``b*`` additionally close the subpath before painting, and
#: that closure is deliberately not recorded: a ``ClosePath`` carries no
#: coordinate, and every consumer of a ``SubPath`` — ``anchors``, ``bbox``,
#: ``fit_circle`` — steps over it. Recording it could not change an answer.
_NO_PAINT_OPS = frozenset({"n"})

#: How deep Form XObjects may nest before we assume a malicious or broken file.
_MAX_FORM_DEPTH = 12


@dataclass(frozen=True, slots=True)
class _LayerPath:
    """One painted subpath in page space, with the layers it was drawn inside."""

    layers: frozenset[str]
    path: SubPath


class AiPdfSource:
    """Reads drill geometry from a PDF-compatible ``.ai`` file.

    ``drill_layer`` supplies the circles; ``reference_layer`` supplies the panel
    outline that defines the canonical frame — millimetres, Y up, origin at the
    outline's centre.
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
        """Painted subpaths on ``layer``, in page space, clips already dropped.

        Exposed because it is the honest unit of what was read: it lets a caller
        (and the tests) see that the artboard-sized clip rectangles never became
        geometry, without having to infer it from the holes that came out.
        """
        names, paths = self._extract()
        self._require_layer(layer, names)
        return tuple(p.path for p in paths if layer in p.layers)

    def read(self) -> RawDrillData:
        """Parse the file into ``RawDrillData`` in the canonical frame."""
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
            # No frame to centre on. Reporting page-space coordinates keeps the
            # numbers true to the file and lets the caller decide; silently
            # falling back to the artboard centre would look plausible and be
            # wrong (SPEC 6.6).
            centre = (0.0, 0.0)
            reference = None
            diagnostics.append(
                Diagnostic.warning(
                    # Not ``no-reference-outline``: ``CheckReferenceSize`` uses
                    # that key at INFO for a different finding — that there was
                    # nothing to check the outline against. ``code`` is the
                    # stable machine key consumers match on (SPEC 3), and one
                    # key meaning two things at two severities defeats it, the
                    # more so because only the WARNING moves the exit code.
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

        # Traversal order is deterministic for a given file, so numbering the
        # circles as they are met gives every hole an identity that is the same
        # on every run — which is what lets a diagnostic name one.
        holes = tuple(
            RawHole(
                x=mm_from_pt(c.cx) - centre[0],
                y=mm_from_pt(c.cy) - centre[1],
                diameter=mm_from_pt(c.diameter),
                index=i,
            )
            for i, c in enumerate(circles)
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

    The property is a name looked up in the *current* resource dictionary's
    ``/Properties`` — current, not the page's, so that a Form XObject carrying
    its own resources still resolves. Anything else (a bare ``BDC /Artifact``,
    an inline dictionary, a dangling name) contributes no layer, which is the
    safe answer: content whose provenance is unclear must not be attributed to
    a layer the designer will then be told it sits on.
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

    Page space here means millimetre-ready PDF points measured from the
    ``/MediaBox`` lower-left corner: the base CTM shifts a non-zero corner back
    to the origin so that coordinates mean the same thing whatever crop
    Illustrator saved.
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

    ``marks`` is the marked-content stack inherited from the caller, so a Form
    XObject invoked inside ``BDC /OC /MC1`` keeps its layer. Inherited is not
    the same as owned: a stream may only close what it opened. An ``EMC`` with
    no ``BDC`` of its own — Illustrator emits them, and so does anything that
    concatenates streams — would otherwise pop the *caller's* entry, and every
    path the form drew after it would come back attributed to no layer at all.
    That is silent: the drill layer simply comes up short.
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
            # Illustrator's streams pop past their own base state; a real file
            # does this and must not take the whole read down with it.
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
            # A deliberate no-op, spelt out rather than left to fall through:
            # clipping is not a painting decision. The operator that ends the
            # path is what says whether it marked ink, and ``n`` is the only one
            # that says no. Nothing about a ``W`` is worth carrying forward.
            pass

        # -- path painting
        elif op in _PAINT_OPS:
            # flush unconditionally: the path ends either way, and leaving it
            # pending would splice it onto whatever is constructed next.
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

    Points are transformed as they arrive rather than at paint time, because the
    CTM in force during construction is the one that counts and a stream may
    (legally) restore a different one before painting.
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
        """End the path and return its subpaths, whether or not it also clips.

        Deciding *here* was the bug. ``W``/``W*`` only adds the path to the
        clipping boundary; what the path marks is settled by the operator that
        ends it, and only ``n`` marks nothing (SPEC 6.3 says ``W`` *followed by*
        ``n``). Discarding on the ``W`` alone silently dropped every ``re W f``
        background outline — leaving the panel with no frame — and every
        ``h W S`` drill circle, whose absence was then reported as a layer that
        needed a stroke it already had. The caller applies ``_NO_PAINT_OPS``.
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

    Malformed operators are skipped rather than raised on: a stream that has
    survived Illustrator's own writer is not worth aborting a whole read for,
    and the geometry that matters is elsewhere in it.
    """
    if operands is None or len(operands) != count:
        return None
    try:
        return [float(v) for v in operands]
    except (TypeError, ValueError):
        return None


def _empty_layer(layer: str, path_count: int) -> EmptyLayerError:
    """The right ``EmptyLayerError`` for why ``layer`` yielded no circle.

    Two very different faults land here and only the source can tell them apart.
    *No paths at all* is the Illustrator trap ``EmptyLayerError`` describes by
    default: unpainted artwork never reaches the PDF stream. *Paths, but none of
    them circular* is a drawing problem — a rounded rectangle, a compound shape,
    an ellipse — and it needs the operator looking at the shapes rather than at
    their appearance settings.
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
    """The bounding box of the biggest path that isn't a circle, or ``None``.

    Circles are excluded because a reference layer legitimately carries them —
    the fixture's Background has two 12 mm ones — and a hole is never the panel.
    Area picks the winner: it is the one measure that cannot be gamed by a long
    thin centreline or a stray tick mark.
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
