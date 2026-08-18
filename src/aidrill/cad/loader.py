"""Load a supplied STEP file into a queryable case model.

The kernel is imported here and nowhere above, so ``import aidrill`` stays
free of it. The lid's play area is intersected with the box's, because a lid
hole is obstructed by the box's bosses once the enclosure is assembled.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..units import Nanometre, nm_from_mm
from .base import CaseModel, Frame, Rejection

__all__ = ["OcpCaseModel", "load_case_model"]


@dataclass
class OcpCaseModel:
    """A kernel-backed case model. Built by :func:`load_case_model`.

    Not frozen, unlike this codebase's value objects: mypy treats a frozen
    dataclass's fields as read-only, which fails structural matching against
    ``CaseModel``'s plain (settable) attributes. Nothing here mutates it.
    """

    part: str
    face: str
    footprint_nm: tuple[Nanometre, Nanometre]
    plate_nm: Nanometre
    play_area_nm: tuple[Nanometre, Nanometre, Nanometre, Nanometre]
    frame: Frame
    margin_nm: Nanometre
    axis: int
    own_region: Any
    own_frame: Frame
    box_region: Any | None
    box_frame: Frame | None
    drilled_face: Any
    #: The drilled face's own extent -- larger than ``play_area_nm``, which is
    #: the inset floor. Separates a hole that misses the panel entirely from
    #: one that lands on it but meets a boss or rib.
    drilled_extent_nm: tuple[Nanometre, Nanometre, Nanometre, Nanometre]
    drilled_position_mm: float
    inner_position_mm: float
    # Beyond the CaseModel protocol: what the emitter needs to cut and write.
    document: Any
    target_shape: Any
    document_timestamp: str

    def classify(
        self, x_nm: Nanometre, y_nm: Nanometre, radius_nm: Nanometre
    ) -> Rejection | None:
        """Reject a hole the casting cannot take, naming which rule refused it.

        A lid's own boundary is drawn tight around the box's corner posts, so
        it can fail on its own right where the box already explains why; the
        box is checked first so that shared cause is reported once, as
        ``OBSTRUCTED``, rather than misread as the lid's own edge or boss.
        """
        from .region import contains

        if self.box_region is not None and self.box_frame is not None and not contains(
            self.box_region, self.box_frame, self.axis, x_nm, y_nm, radius_nm, self.margin_nm
        ):
            return Rejection.OBSTRUCTED
        if not contains(
            self.own_region, self.own_frame, self.axis, x_nm, y_nm, radius_nm, self.margin_nm
        ):
            if self._within_drilled_extent(x_nm, y_nm, radius_nm):
                return Rejection.THROUGH_BOSS
            return Rejection.OFF_FACE
        return None

    def _within_drilled_extent(
        self, x_nm: Nanometre, y_nm: Nanometre, radius_nm: Nanometre
    ) -> bool:
        """Does the grown circle still land on the drilled face itself?

        The floor's own inset boundary already ruled this hole out; this
        tells apart a hole that meets a boss on the plate (still within the
        panel's own outer edge) from one that has run off the panel entirely.
        """
        x0, y0, x1, y1 = self.drilled_extent_nm
        clearance = Nanometre(radius_nm + self.margin_nm)
        return (
            x0 + clearance <= x_nm <= x1 - clearance
            and y0 + clearance <= y_nm <= y1 - clearance
        )


def load_case_model(
    path: Path, *, face: str, margin_nm: Nanometre, part: str | None = None
) -> CaseModel:
    """Read ``path`` and build the model for the named face."""
    from .case import build_frame, find_faces, select_solid
    from .region import build_region, region_bbox_nm
    from .step import read_step, require_kernel

    require_kernel()
    document = read_step(path)
    footprint_nm, axis = _footprint_and_axis(document)

    solid = select_solid(document, face)
    faces = find_faces(solid, axis)
    own_region = build_region(faces.inner, axis, margin_nm)
    own_frame = build_frame(faces, axis)
    drilled_extent_nm = region_bbox_nm(faces.drilled, own_frame, axis)

    box_region = box_frame = None
    if face == "lid":
        box_faces = find_faces(select_solid(document, "box"), axis)
        box_region = build_region(box_faces.inner, axis, margin_nm)
        box_frame = build_frame(box_faces, axis)

    return OcpCaseModel(
        part=part or _part_of(solid.name),
        face=face,
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
        drilled_face=faces.drilled,
        drilled_extent_nm=drilled_extent_nm,
        drilled_position_mm=faces.drilled_position_mm,
        inner_position_mm=faces.inner_position_mm,
        document=document.document,
        target_shape=solid.shape,
        document_timestamp=document.timestamp,
    )


def _footprint_and_axis(document: Any) -> tuple[tuple[Nanometre, Nanometre], int]:
    """Measure the assembly's footprint and the axis normal to it."""
    from .case import assembly_spans, drill_axis

    spans = assembly_spans(document)
    axis = min(range(3), key=lambda index: spans[index])
    in_plane = sorted((spans[i] for i in range(3) if i != axis), reverse=True)
    footprint = (nm_from_mm(in_plane[0]), nm_from_mm(in_plane[1]))
    return footprint, drill_axis(document, footprint)


def _part_of(product_name: str) -> str:
    """The designator a product name begins with, or the whole name."""
    return product_name.split()[0] if product_name.split() else product_name
