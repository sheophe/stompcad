"""The pure values, and the two rules that are arithmetic rather than shape."""

from __future__ import annotations

import dataclasses
import math

import pytest

from stompcollider.model import (
    Board,
    Clash,
    Component,
    Correspondence,
    DockData,
    Placement,
    Profile,
    Protrusion,
)
from stompmodel.diagnostics import Diagnostic, Severity, of_severity, worst_severity
from stompmodel.frames import CoordinateFrame, FaceFrame
from stompmodel.model import CaseFace, CaseRegistration, StageRun
from stompmodel.protocols import Diagnosable, Processable
from stompmodel.units import Nanometre


def _profile(*steps: tuple[int, int, int]) -> Profile:
    return Profile(tuple((Nanometre(r), Nanometre(lo), Nanometre(hi)) for r, lo, hi in steps))


#: A 5 mm LED: 4.9 to the flange at 3 mm, then 5.8 beyond it.
_LED = _profile((2_450_000, 0, 3_000_000), (2_900_000, 3_000_000, 8_000_000))


def test_radius_at_takes_the_greatest_step_covering_that_depth() -> None:
    """Greatest, not last and not first: steps may overlap in depth."""
    assert _LED.radius_at(Nanometre(1_000_000)) == Nanometre(2_450_000)
    assert _LED.radius_at(Nanometre(5_000_000)) == Nanometre(2_900_000)


def test_insertion_is_the_least_depth_at_which_the_profile_exceeds_the_hole() -> None:
    """The LED's flange is the feature that must NOT pass: a 5 mm hole seats
    on it at 3 mm, while a 6 mm hole admits the whole part."""
    assert _LED.insertion_through(Nanometre(2_500_000)) == Nanometre(3_000_000)
    assert _LED.insertion_through(Nanometre(3_000_000)) is None


def test_a_largest_radius_rule_would_name_the_flange() -> None:
    """The clause that distinguishes this from the rule the spec rejects: the
    greatest radius in the stack is 5.8, which no 5 mm hole admits at all."""
    assert max(step[0] for step in _LED.steps) == Nanometre(2_900_000)
    assert _LED.insertion_through(Nanometre(2_500_000)) is not None


def test_insertion_never_increases_as_the_hole_narrows() -> None:
    """A property the spec names. Monotone by construction, so a regression
    here means radius_at stopped taking the greatest step."""
    depths = [_LED.insertion_through(Nanometre(radius)) for radius in range(2_400_000, 3_000_000, 50_000)]
    finite = [d for d in depths if d is not None]
    assert finite == sorted(finite)


def test_a_profile_with_no_steps_is_refused() -> None:
    """A component with no admissible cylinder has no profile; it must not be
    representable as an empty one that silently inserts to zero depth."""
    with pytest.raises(ValueError, match="at least one step"):
        Profile(())


def test_a_profile_step_rejects_a_non_integer_nanometre() -> None:
    """ADR-0004: a length that never crossed the mm->nm boundary is the
    defect ``check_nanometres`` exists to catch, not a value to coerce."""
    with pytest.raises(TypeError):
        Profile(((Nanometre(1), Nanometre(0), 1.5),))  # type: ignore[arg-type]


def test_a_profile_is_frozen() -> None:
    profile = _profile((1, 0, 1))
    with pytest.raises(dataclasses.FrozenInstanceError):
        profile.steps = ()  # type: ignore[misc]


def test_a_profile_is_slotted() -> None:
    """Frozen alone already refuses ``instance.attr = value``; slotted is the
    separate claim that no ``__dict__`` exists to fall back on, which only a
    ``__setattr__``-bypassing mutation can show."""
    profile = _profile((1, 0, 1))
    with pytest.raises(AttributeError):
        object.__setattr__(profile, "extra", 1)


# --------------------------------------------------------------------------
# Protrusion
# --------------------------------------------------------------------------


def _profile_simple() -> Profile:
    return _profile((1_000_000, 0, 1_000_000))


def test_protrusion_requires_a_designator() -> None:
    with pytest.raises(ValueError, match="designator"):
        Protrusion("", (Nanometre(0), Nanometre(0)), _profile_simple())


def test_protrusion_axis_must_have_two_components() -> None:
    with pytest.raises(ValueError, match="two components"):
        Protrusion("D1", (Nanometre(0),), _profile_simple())  # type: ignore[arg-type]


def test_protrusion_axis_rejects_a_non_integer_nanometre() -> None:
    with pytest.raises(TypeError):
        Protrusion("D1", (Nanometre(0), 0.5), _profile_simple())  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Component
# --------------------------------------------------------------------------


def test_component_requires_a_designator() -> None:
    with pytest.raises(ValueError, match="designator"):
        Component("", None)


def test_component_may_have_no_protrusion() -> None:
    assert Component("D1", None).protrusion is None


def test_component_carries_its_protrusion() -> None:
    protrusion = Protrusion("D1", (Nanometre(0), Nanometre(0)), _profile_simple())
    assert Component("D1", protrusion).protrusion is protrusion


# --------------------------------------------------------------------------
# Board
# --------------------------------------------------------------------------


def _frame() -> CoordinateFrame:
    return CoordinateFrame(
        origin_nm=(Nanometre(0), Nanometre(0), Nanometre(0)),
        u=(1.0, 0.0, 0.0),
        v=(0.0, 1.0, 0.0),
        w=(0.0, 0.0, 1.0),
    )


def _extent() -> tuple[Nanometre, Nanometre, Nanometre]:
    return (Nanometre(1_000_000), Nanometre(2_000_000), Nanometre(300_000))


def test_board_requires_a_positive_ordinal() -> None:
    with pytest.raises(ValueError, match="numbered from 1"):
        Board(0, ("D1",), _extent(), _frame(), (Component("D1", None),))


def test_board_requires_at_least_one_designator() -> None:
    with pytest.raises(ValueError, match="designator"):
        Board(1, (), _extent(), _frame(), (Component("D1", None),))


def test_board_extent_must_have_three_components() -> None:
    with pytest.raises(ValueError, match="three components"):
        Board(1, ("D1",), (Nanometre(1), Nanometre(1)), _frame(), (Component("D1", None),))  # type: ignore[arg-type]


def test_board_extent_rejects_a_non_integer_nanometre() -> None:
    with pytest.raises(TypeError):
        Board(1, ("D1",), (Nanometre(1), Nanometre(1), 1.0), _frame(), (Component("D1", None),))  # type: ignore[arg-type]


def test_board_carries_every_designator_and_component_not_just_the_first() -> None:
    """Vacuity hazard: a single-component board passes an implementation
    that quietly drops every component but the first."""
    components = (Component("D1", None), Component("D2", None))
    board = Board(1, ("D1", "D2"), _extent(), _frame(), components)
    assert board.designators == ("D1", "D2")
    assert board.components == components


# --------------------------------------------------------------------------
# Correspondence
# --------------------------------------------------------------------------


def _correspondence(designator: str = "D1", hole_index: int = 1) -> Correspondence:
    return Correspondence(
        designator, hole_index, (Nanometre(0), Nanometre(0)), Nanometre(0), Nanometre(0)
    )


def test_correspondence_requires_a_designator() -> None:
    with pytest.raises(ValueError, match="designator"):
        Correspondence("", 1, (Nanometre(0), Nanometre(0)), Nanometre(0), Nanometre(0))


def test_correspondence_hole_index_is_numbered_from_one() -> None:
    with pytest.raises(ValueError, match="numbered from 1"):
        Correspondence("D1", 0, (Nanometre(0), Nanometre(0)), Nanometre(0), Nanometre(0))


def test_correspondence_hole_xy_must_have_two_components() -> None:
    with pytest.raises(ValueError, match="two components"):
        Correspondence("D1", 1, (Nanometre(0),), Nanometre(0), Nanometre(0))  # type: ignore[arg-type]


def test_correspondence_rejects_a_non_integer_nanometre() -> None:
    with pytest.raises(TypeError):
        Correspondence("D1", 1, (Nanometre(0), Nanometre(0)), 0.5, Nanometre(0))  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Clash
# --------------------------------------------------------------------------


def _bbox() -> tuple[Nanometre, ...]:
    return tuple(Nanometre(v) for v in (-1_000, -2_000, -3_000, 4_000, 5_000, 6_000))


def test_clash_requires_a_named_other_solid() -> None:
    with pytest.raises(ValueError, match="against"):
        Clash("", "case", _bbox(), Nanometre(0), "w", 0)


def test_clash_requires_a_kind() -> None:
    with pytest.raises(ValueError, match="kind"):
        Clash("LID", "", _bbox(), Nanometre(0), "w", 0)


def test_clash_requires_an_axis() -> None:
    with pytest.raises(ValueError, match="axis"):
        Clash("LID", "case", _bbox(), Nanometre(0), "", 0)


def test_clash_rejects_a_non_integer_bbox_component() -> None:
    bad = (Nanometre(0), Nanometre(0), Nanometre(0), Nanometre(1), Nanometre(1), 1.0)
    with pytest.raises(TypeError):
        Clash("LID", "case", bad, Nanometre(0), "w", 0)  # type: ignore[arg-type]


def test_clash_carries_every_bbox_component_not_just_the_first() -> None:
    bbox = _bbox()
    clash = Clash("LID", "case", bbox, Nanometre(1), "w", 1)
    assert clash.bbox_nm == bbox


# --------------------------------------------------------------------------
# Placement
# --------------------------------------------------------------------------


def test_placement_requires_a_positive_rank() -> None:
    with pytest.raises(ValueError, match="ranked from 1"):
        Placement(0, Nanometre(0), Nanometre(0), Nanometre(0), 0.0, (), ())


def test_placement_theta_must_be_finite() -> None:
    with pytest.raises(TypeError, match="finite"):
        Placement(1, Nanometre(0), Nanometre(0), Nanometre(0), math.nan, (), ())


def test_placement_theta_must_be_a_float_not_an_int() -> None:
    """ADR-0004's exactness discipline applied to the one plain float this
    document carries: an int slipping through would format identically only
    by accident."""
    with pytest.raises(TypeError, match="finite"):
        Placement(1, Nanometre(0), Nanometre(0), Nanometre(0), 0, (), ())  # type: ignore[arg-type]


def test_placement_carries_every_correspondence_not_just_the_first() -> None:
    """Vacuity hazard: a single-correspondence placement passes an
    implementation that quietly drops every correspondence but the first."""
    correspondences = (_correspondence("D1", 1), _correspondence("D2", 2))
    placement = Placement(1, Nanometre(0), Nanometre(0), Nanometre(0), 0.0, correspondences, ())
    assert placement.correspondence == correspondences


# --------------------------------------------------------------------------
# DockData
# --------------------------------------------------------------------------


def _case() -> CaseRegistration:
    return CaseRegistration("1590BB", CaseFace.BOX, "1590BB.stp", FaceFrame(_frame()))


def test_dockdata_requires_a_case() -> None:
    with pytest.raises(TypeError):
        DockData()  # type: ignore[call-arg]


def test_dockdata_defaults_are_empty() -> None:
    data = DockData(_case())
    assert data.boards == ()
    assert data.placements == {}
    assert data.unmatched_holes == ()
    assert data.diagnostics == ()
    assert data.processing == ()


def test_dockdata_unmatched_holes_are_numbered_from_one() -> None:
    with pytest.raises(ValueError, match="numbered from 1"):
        DockData(_case(), unmatched_holes=(0,))


def test_dockdata_placements_are_keyed_by_board_ordinal() -> None:
    """The workspace rule -- no dict key holds a float -- is a static one
    here: ``placements`` is typed ``dict[int, ...]``, the same discipline
    ``Hole.index`` relies on mypy for rather than a runtime type check."""
    placement = Placement(1, Nanometre(0), Nanometre(0), Nanometre(0), 0.0, (), ())
    data = DockData(_case(), placements={1: (placement,)})
    assert data.placements[1] == (placement,)


def test_dockdata_is_frozen() -> None:
    data = DockData(_case())
    with pytest.raises(dataclasses.FrozenInstanceError):
        data.boards = ()  # type: ignore[misc]


def test_dockdata_is_slotted() -> None:
    data = DockData(_case())
    with pytest.raises(AttributeError):
        object.__setattr__(data, "extra", 1)


def test_dockdata_with_processing_appends_in_order() -> None:
    data = DockData(_case()).with_processing(StageRun("match")).with_processing(StageRun("seat"))
    assert [run.name for run in data.processing] == ["match", "seat"]


def test_dockdata_with_processing_with_no_runs_returns_self() -> None:
    data = DockData(_case())
    assert data.with_processing() is data


def test_dockdata_with_diagnostics_appends() -> None:
    data = DockData(_case()).with_diagnostics(Diagnostic.error("no-correspondence", "wrong board"))
    assert len(data.diagnostics) == 1


def test_dockdata_with_diagnostics_with_none_returns_self() -> None:
    data = DockData(_case())
    assert data.with_diagnostics() is data


def test_dockdata_satisfies_both_processable_and_diagnosable() -> None:
    data = DockData(_case())
    assert isinstance(data, Processable)
    assert isinstance(data, Diagnosable)


def _some_diagnostics() -> tuple[Diagnostic, ...]:
    return (
        Diagnostic.warning("off-size", "board larger than declared"),
        Diagnostic.error("no-correspondence", "wrong board for this case"),
        Diagnostic.info("zero-clearance", "interference fit by design"),
    )


@pytest.mark.parametrize("severity", list(Severity))
def test_dockdata_of_severity_matches_the_published_function(severity: Severity) -> None:
    """One implementation of 'of this severity' exists in the workspace."""
    diagnostics = _some_diagnostics()
    data = DockData(_case(), diagnostics=diagnostics)
    assert data.of_severity(severity) == of_severity(diagnostics, severity)


def test_dockdata_worst_severity_matches_the_published_function() -> None:
    diagnostics = _some_diagnostics()
    data = DockData(_case(), diagnostics=diagnostics)
    assert data.worst_severity == worst_severity(diagnostics)


def test_dockdata_worst_severity_matches_the_published_function_when_empty() -> None:
    data = DockData(_case())
    assert data.worst_severity == worst_severity(()) is None
