"""Load a supplied STEP file into a queryable case model.

The kernel is imported here and nowhere above, so ``import stompdrill`` stays
free of it. A lid hole is checked against the box's own region too, because
it would be obstructed by what sits behind it once the enclosure is
assembled; ``play_area_nm`` still reports only the drilled part's own play
area -- it is provenance for that one face, not the combined check.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from stompmodel.frames import FaceFrame
from stompmodel.model import CaseFace, DrilledSurface
from stompmodel.units import Nanometre, nm_from_mm

from ..errors import StompdrillError
from .base import Rejection

__all__ = ["OcpCaseModel", "load_case_model"]

_THROUGH: frozenset[str] = frozenset({"structure", "concave"})


@dataclass(frozen=True, slots=True)
class OcpCaseModel:
    """A kernel-backed case model. Built by :func:`load_case_model`."""

    part: str
    face: CaseFace
    model_name: str
    footprint_nm: tuple[Nanometre, Nanometre]
    plate_nm: Nanometre
    play_area_nm: tuple[Nanometre, Nanometre, Nanometre, Nanometre]
    frame: FaceFrame
    margin_nm: Nanometre
    axis: int
    own_region: Any
    own_frame: FaceFrame
    box_region: Any | None
    box_frame: FaceFrame | None
    drilled_position_mm: float
    inner_position_mm: float
    # Beyond the CaseModel protocol: what the emitter needs to cut and write.
    document: Any
    # ``cut_shape`` deliberately does not read this back (see its own
    # docstring): it locates the drilled solid by walking the document's own
    # label tree, not by comparing against a shape captured at load time.
    # Kept anyway as an independent handle a test can use to confirm ``emit``
    # leaves the supplied model's own solid pristine, without relying on the
    # same label-tree walk the code under test uses to make that change.
    target_shape: Any
    document_timestamp: str
    #: Every wall this model discovered, each as the record a document carries.
    #: A tuple and not a mapping, so the order discovery fixed is the order a
    #: consumer sees (ADR-0006). Empty for a model whose walls could not be
    #: discovered or framed (a lid with nothing behind its lateral levels to
    #: face, say) as well as for one built without wall support at all -- both
    #: are "no walls" to a consumer, and neither can express anything a
    #: default would lose.
    walls: tuple[DrilledSurface, ...] = ()
    #: Each wall's outer and inner drillable region, keyed by surface. Two,
    #: because a hole coaxial with its component crosses the two planes at
    #: different places and must clear the region at each (decision 8).
    wall_regions: Mapping[str, tuple[Any, Any]] = MappingProxyType({})
    #: Why ``walls`` is empty, when discovery was attempted and refused; ``None``
    #: when it found its walls. Kept because a consumer must tell an enclosure
    #: whose walls could not be determined from a seating that missed them.
    walls_unavailable: str | None = None

    def classify(
        self, x_nm: Nanometre, y_nm: Nanometre, radius_nm: Nanometre
    ) -> Rejection | None:
        """Reject a hole the casting cannot take, naming which rule refused it.

        The drilled part's own face decides first: ``OFF_FACE`` or
        ``THROUGH_BOSS`` for a failure against its own boundary. Only a hole
        its own face accepts is then checked against what sits behind it --
        an ``OBSTRUCTED`` verdict never overrides what the part's own
        geometry already refused for a different reason.
        """
        from .region import clearance_reason, contains

        if not contains(
            self.own_region, self.own_frame, self.axis, x_nm, y_nm, radius_nm, self.margin_nm
        ):
            reason = clearance_reason(self.own_region, self.own_frame, self.axis, x_nm, y_nm)
            return Rejection.THROUGH_BOSS if reason in _THROUGH else Rejection.OFF_FACE
        if self.box_region is None or self.box_frame is None:
            return None
        # A box and its lid are viewed from opposite sides, so the same
        # canonical x is a different model x on each; restate the point in
        # the box's own frame before testing it against the box's region.
        box_x, box_y = self.own_frame.basis.reframe(x_nm, y_nm, self.box_frame.basis)
        if not contains(
            self.box_region, self.box_frame, self.axis, box_x, box_y, radius_nm, self.margin_nm
        ):
            return Rejection.OBSTRUCTED
        return None

    def admits(self, key: str, x_nm: Nanometre, y_nm: Nanometre) -> bool:
        """Whether this point lies in that wall's outer drillable region at all.

        A point and not a circle: picking which wall a ray reaches comes before
        the hole has a radius, because the radius depends on the wall's own
        span. ``classify_wall`` is what asks the sized question.
        """
        from .region import contains_at_depth

        surface = self._wall(key)
        outer, _inner = self.wall_regions[key]
        return contains_at_depth(
            outer, surface.frame, x_nm, y_nm, surface.thickness_nm,
            Nanometre(0), Nanometre(0),
        )

    def classify_wall(
        self,
        key: str,
        outer_nm: tuple[Nanometre, Nanometre],
        inner_nm: tuple[Nanometre, Nanometre],
        radius_nm: Nanometre,
    ) -> Rejection | None:
        """Refuse a sized wall hole, naming which rule refused it.

        The outer region first, since that is the surface a builder marks and
        the one the document's bounds state; then the inner, at the place the
        same axis crosses *it* -- the outer face is the larger of the two on
        every wall of every catalogued model, so the outer alone would accept a
        hole that leaves the inner. A failure against what stands behind the
        wall reads as ``THROUGH_BOSS``, as it does on the plate.
        """
        from .region import contains_at_depth

        surface = self._wall(key)
        outer, inner = self.wall_regions[key]
        if not contains_at_depth(
            outer, surface.frame, outer_nm[0], outer_nm[1],
            surface.thickness_nm, radius_nm, self.margin_nm,
        ):
            return Rejection.OFF_FACE
        if not contains_at_depth(
            inner, surface.frame, inner_nm[0], inner_nm[1],
            Nanometre(0), radius_nm, self.margin_nm,
        ):
            return Rejection.THROUGH_BOSS
        return None

    def _wall(self, key: str) -> DrilledSurface:
        """The record for one wall, or a refusal naming what was asked for."""
        for surface in self.walls:
            if surface.key == key:
                return surface
        raise StompdrillError(f"this model discovered no {key} wall")


def load_case_model(
    path: Path, *, face: CaseFace, margin_nm: Nanometre, part: str | None = None
) -> OcpCaseModel:
    """Read ``path`` and build the model for the named face."""
    from stompgeom import kernel
    from stompgeom.step import read_step

    from .case import build_frame, find_faces, select_solid
    from .region import build_region, region_bbox_nm
    from .walls import build_wall_frame, drilled_surface, find_walls, nearest_axis, surface_key

    kernel.require_kernel()
    document = read_step(path)
    footprint_nm, axis = _footprint_and_axis(document)

    solid = select_solid(document, face)
    faces = find_faces(solid, axis)
    own_region = build_region(faces.inner, axis, faces.outward[axis])
    own_frame = build_frame(faces, axis)

    box_region = box_frame = None
    if face is CaseFace.LID:
        box_faces = find_faces(select_solid(document, CaseFace.BOX), axis)
        box_region = build_region(box_faces.inner, axis, box_faces.outward[axis])
        box_frame = build_frame(box_faces, axis)

    walls: list[DrilledSurface] = []
    regions: dict[str, tuple[Any, Any]] = {}
    unavailable: str | None = None
    try:
        # The whole answer, not just its first step: framing a wall, keying it,
        # building its two regions and stating its record can each refuse, and
        # a model that reached one of those is as much "no walls" as one whose
        # walls were never found. A lid is the ordinary case -- a flat closure
        # plate with nothing behind its lateral levels to face, which is a fact
        # about the lid and not a load failure. Wall drilling is opt-in, and a
        # feature naming an unreachable wall is refused by ``DrillWalls``
        # itself (``wall-feature-unreachable``), which is where that diagnostic
        # belongs -- not here, blocking a load the panel's face never needed.
        for wall in find_walls(solid, axis):
            lateral = nearest_axis(wall.outward)
            wall_axis_index = max(range(3), key=lambda index: abs(lateral[index]))
            frame = build_wall_frame(wall, faces.outward)
            key = surface_key(wall, own_frame)
            outer = build_region(
                wall.outer_faces, wall_axis_index, wall.outward[wall_axis_index]
            )
            inner = build_region(
                wall.inner, wall_axis_index, wall.outward[wall_axis_index]
            )
            walls.append(drilled_surface(wall, key, frame, outer))
            regions[key] = (outer, inner)
    except StompdrillError as refusal:
        unavailable = str(refusal)
        # Partly built walls are discarded rather than kept: a model reporting
        # three of its four walls would let a ray resolve to whichever of them
        # survived, and a hole would be cut from an incomplete enclosure.
        walls, regions = [], {}

    return OcpCaseModel(
        part=part or _part_of(solid.name),
        face=face,
        model_name=path.name,
        footprint_nm=footprint_nm,
        plate_nm=faces.plate_nm,
        play_area_nm=region_bbox_nm(own_region, own_frame, axis),
        frame=own_frame,
        margin_nm=margin_nm,
        axis=axis,
        own_region=own_region,
        own_frame=own_frame,
        box_region=box_region,
        box_frame=box_frame,
        drilled_position_mm=faces.drilled_position_mm,
        inner_position_mm=faces.inner_position_mm,
        document=document.document,
        target_shape=solid.shape,
        document_timestamp=document.timestamp,
        walls=tuple(walls),
        wall_regions=MappingProxyType(regions),
        walls_unavailable=unavailable,
    )


def _footprint_and_axis(document: Any) -> tuple[tuple[Nanometre, Nanometre], int]:
    """Measure the assembly's footprint and the axis normal to it."""
    from stompgeom.step import assembly_spans

    from .case import drill_axis

    spans = assembly_spans(document)
    axis = min(range(3), key=lambda index: spans[index])
    in_plane = sorted((spans[i] for i in range(3) if i != axis), reverse=True)
    footprint = (nm_from_mm(in_plane[0]), nm_from_mm(in_plane[1]))
    return footprint, drill_axis(document, footprint)


def _part_of(product_name: str) -> str:
    """The designator a product name begins with, or the whole name."""
    return product_name.split()[0] if product_name.split() else product_name
