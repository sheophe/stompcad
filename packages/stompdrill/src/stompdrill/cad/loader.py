"""Load a supplied STEP file into a queryable case model.

The kernel is imported here and nowhere above, so ``import stompdrill`` stays
free of it. A lid hole is checked against the box's own region too, because
it would be obstructed by what sits behind it once the enclosure is
assembled; ``play_area_nm`` still reports only the drilled part's own play
area -- it is provenance for that one face, not the combined check.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from stompmodel.frames import FaceFrame
from stompmodel.units import Nanometre, nm_from_mm

from .base import Rejection

__all__ = ["OcpCaseModel", "load_case_model"]

_THROUGH: frozenset[str] = frozenset({"structure", "concave"})


@dataclass(frozen=True, slots=True)
class OcpCaseModel:
    """A kernel-backed case model. Built by :func:`load_case_model`."""

    part: str
    face: str
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


def load_case_model(
    path: Path, *, face: str, margin_nm: Nanometre, part: str | None = None
) -> OcpCaseModel:
    """Read ``path`` and build the model for the named face."""
    from stompgeom import kernel
    from stompgeom.step import read_step

    from .case import build_frame, find_faces, select_solid
    from .region import build_region, region_bbox_nm

    kernel.require_kernel()
    document = read_step(path)
    footprint_nm, axis = _footprint_and_axis(document)

    solid = select_solid(document, face)
    faces = find_faces(solid, axis)
    own_region = build_region(faces.inner, axis, faces.outward[axis])
    own_frame = build_frame(faces, axis)

    box_region = box_frame = None
    if face == "lid":
        box_faces = find_faces(select_solid(document, "box"), axis)
        box_region = build_region(box_faces.inner, axis, box_faces.outward[axis])
        box_frame = build_frame(box_faces, axis)

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
