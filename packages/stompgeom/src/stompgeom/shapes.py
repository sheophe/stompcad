"""Making one shape out of others: bundling, locating, intersecting.

The topological side of geometry, as distinct from the format side that
reads and writes STEP. Every operation here is describable without naming a
panel or a board, which is ADR-0008's admission test.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from stompmodel.frames import RigidTransform

from .errors import StompgeomError
from .kernel import require_kernel

__all__ = [
    "compound", "placed", "common", "interferes", "volume_mm3",
    "centre_of_mass_mm",
]

#: The tolerance :func:`interferes` runs its boolean at, in millimetres.
#: Part of that predicate's definition rather than a setting: at the
#: kernel's default an ill-conditioned pose -- a bushing standing 0.027 mm
#: proud in its own bore -- returns an empty shape for a region it really
#: holds, which a volume predicate reads as a way through. Measured on the
#: tar assembly, one potentiometer against the drilled 1590B box, over
#: 0.1 mm steps of that board's insertion path: at the kernel's default the
#: shared volume reads nothing, 0.166, nothing, 3.289 mm^3 at four
#: consecutive poses, and at this tolerance 0.1059, 0.1059, 0.1059,
#: 0.0900 -- one of those two is a continuous overlap and the other is a
#: boolean failing. It does not manufacture interference where there is
#: none: a 12.000 mm bush in a 12.000 mm hole reads identically at both
#: tolerances, at every depth, which is the control beside this figure.
_INTERFERENCE_FUZZ_MM = 1e-4


def compound(shapes: Iterable[Any]) -> Any:
    """Bundle ``shapes`` into one ``TopoDS_Compound``, in the order given.

    An empty iterable yields an empty compound rather than raising: a level
    with no faces is a legitimate value, and refusing it here would push the
    same check into every caller.
    """
    require_kernel()
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound

    built = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(built)
    for shape in shapes:
        builder.Add(built, shape)
    return built


def placed(shape: Any, motion: RigidTransform) -> Any:
    """A located copy of ``shape`` under ``motion``.

    A ``TopLoc_Location`` rather than a rebuilt transform: locating
    rebuilds no geometry, so the writer still sees the original topology
    and the names and colours attached to it survive the placement.
    """
    require_kernel()
    from OCP.gp import gp_Trsf
    from OCP.TopLoc import TopLoc_Location

    trsf = gp_Trsf()
    rows = motion.rotation
    trsf.SetValues(
        rows[0][0], rows[0][1], rows[0][2], motion.translation_mm[0],
        rows[1][0], rows[1][1], rows[1][2], motion.translation_mm[1],
        rows[2][0], rows[2][1], rows[2][2], motion.translation_mm[2],
    )
    return shape.Moved(TopLoc_Location(trsf))


def common(first: Any, second: Any) -> Any | None:
    """The region ``first`` and ``second`` share, or ``None`` when they share none.

    An exact boolean, never a bounding-box estimate. Either side may be a
    sequence, which is several operands rather than one shape -- see
    :func:`_operands` for when that matters. ``None`` rather than the empty
    compound the kernel hands back: that shape carries no topology at all,
    so a caller reading a bounding box off it gets an exception instead of a
    fact. Two bodies in contact -- meeting on a face, or a shaft exactly
    filling its bore -- share no region and arrive here as ``None``. Like
    :func:`interferes` it leaves its arguments as it found them.
    """
    require_kernel()
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common

    arguments, tools = _operands(first), _operands(second)
    if not arguments or not tools:
        return None
    operation = BRepAlgoAPI_Common()
    operation.SetArguments(_listed(arguments))
    operation.SetTools(_listed(tools))
    # Non-destructive for the reason :func:`interferes` is: a located copy
    # shares a ``TShape`` with the solid it came from, so a boolean allowed
    # to modify its arguments rewrites the geometry every later query of
    # those same solids reads. Measured: with this off, one board seated at
    # contact read as interfering *after* its clash region had been
    # measured, and read as clear before -- one pose, two answers.
    operation.SetNonDestructive(True)
    operation.Build()
    if not operation.IsDone():
        raise StompgeomError("the shared region of two shapes could not be evaluated")
    return _region(operation.Shape())


def _operands(side: Any) -> list[Any]:
    """One side of a boolean as the list of operands the kernel takes.

    A sequence is that list; anything else is one operand, a compound
    included. **The distinction is the caller's to make, and it costs.**
    Handed a compound whose members intersect *each other* the kernel reads
    a self-intersecting argument and answers nothing at all -- silently, for
    a pair that really does share a region -- so a bundle whose members may
    meet must be passed as a sequence. Passing one that cannot is worth it:
    measured on the tar board's forty solids against one case solid, one
    compound answers in 21.9 s and forty operands in 40.8 s, because the
    kernel intersects the operands with one another first.
    """
    return list(side) if isinstance(side, (list, tuple)) else [side]


def _listed(shapes: list[Any]) -> Any:
    """``shapes`` as the kernel's own list type, in the order given."""
    from OCP.TopTools import TopTools_ListOfShape

    listed = TopTools_ListOfShape()
    for shape in shapes:
        listed.Append(shape)
    return listed


def _region(shape: Any) -> Any | None:
    """A boolean's result, or ``None`` where it carries no topology at all.

    Emptiness asked topologically rather than by bounding box: every
    non-empty result has at least one vertex, whatever its dimension, and a
    void ``Bnd_Box`` cannot be read without raising. Shared by both
    booleans below so one rule decides what empty means.
    """
    from OCP.TopAbs import TopAbs_ShapeEnum
    from OCP.TopExp import TopExp_Explorer

    if shape.IsNull() or not TopExp_Explorer(shape, TopAbs_ShapeEnum.TopAbs_VERTEX).More():
        return None
    return shape


def interferes(first: Any, second: Any) -> bool:
    """Whether ``first`` and ``second`` share positive volume.

    Its own entry point rather than switches on :func:`common`, because
    both settings belong to *this* question. Asked of one pair at many
    poses, the boolean must be non-destructive: a located copy shares a
    ``TShape`` with the solid it came from. It must also carry a fuzzy
    value, or an ill-conditioned pose reports nothing where it holds a
    region -- measured, and see the fuzz note above. Contact is not
    interference and stays so: two bodies meeting on a surface share no
    volume and this is ``False``. Either side may be a sequence of shapes,
    which is several operands rather than one -- see :func:`_operands`.
    """
    require_kernel()
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common

    arguments, tools = _operands(first), _operands(second)
    if not arguments or not tools:
        return False
    operation = BRepAlgoAPI_Common()
    operation.SetArguments(_listed(arguments))
    operation.SetTools(_listed(tools))
    operation.SetNonDestructive(True)
    operation.SetFuzzyValue(_INTERFERENCE_FUZZ_MM)
    operation.Build()
    if not operation.IsDone():
        raise StompgeomError("two shapes could not be tested for interference")
    region = _region(operation.Shape())
    return region is not None and volume_mm3(region) > 0.0


def volume_mm3(shape: Any) -> float:
    """How much material ``shape`` holds, in cubic millimetres.

    Read off the exact geometry by Gauss integration over its faces, never
    off a triangulation: a quantity read from a mesh is a function of the
    deflection it was built at rather than of the input. A region with no
    thickness -- two bodies meeting on a face -- holds nothing and measures
    zero, which is the same answer :func:`common` gives by handing back
    ``None`` before a caller ever gets here.
    """
    require_kernel()
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    properties = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, properties)
    return float(properties.Mass())


def centre_of_mass_mm(shape: Any) -> tuple[float, float, float]:
    """Where ``shape``'s material sits, in millimetres.

    The same exact integration :func:`volume_mm3` reads its answer from, so
    a caller asking where a solid *is* and one asking how much of it there
    is get one measurement rather than two that could disagree. Never a
    bounding-box centre: a plate and a screw of the same box hold their
    material in different places, which is exactly the distinction a caller
    reaching for this is drawing.
    """
    require_kernel()
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    properties = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, properties)
    centre = properties.CentreOfMass()
    return (float(centre.X()), float(centre.Y()), float(centre.Z()))
