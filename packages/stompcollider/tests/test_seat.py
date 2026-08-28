"""Seat: how deep a board goes, and in what order placements are reported.

Fixtures are hand-built, no kernel, no fixture file -- ``Placement`` and
``Clash`` are pure value objects, so the ranking key can be exercised
directly even though no clash detector exists yet. Positions are chosen to
avoid every vacuity hazard the task names -- see the comment above each
fixture group for which hazard it targets.
"""

from __future__ import annotations

from stompcollider.model import Clash, Correspondence, DockData, Placement
from stompcollider.seat import Seat, rank_key
from stompmodel.frames import CoordinateFrame, FaceFrame
from stompmodel.model import CaseFace, CaseRegistration, StageRun
from stompmodel.protocols import Stage
from stompmodel.units import Nanometre

# --------------------------------------------------------------------------
# Shared builders
# --------------------------------------------------------------------------


def _nm(value: int) -> Nanometre:
    return Nanometre(value)


def _identity_frame() -> CoordinateFrame:
    return CoordinateFrame(
        origin_nm=(Nanometre(0), Nanometre(0), Nanometre(0)),
        u=(1.0, 0.0, 0.0),
        v=(0.0, 1.0, 0.0),
        w=(0.0, 0.0, 1.0),
    )


def _case() -> CaseRegistration:
    return CaseRegistration("1590BB", CaseFace.BOX, "test.stp", FaceFrame(_identity_frame()))


def _correspondence(designator: str, insertion_nm: int | None, hole_index: int) -> Correspondence:
    return Correspondence(
        designator=designator,
        hole_index=hole_index,
        hole_xy_nm=(_nm(0), _nm(0)),
        insertion_nm=None if insertion_nm is None else _nm(insertion_nm),
        offset_nm=_nm(0),
    )


def _clash(volume_nm3: int = 0, depth_nm: int = 0, with_: str = "case") -> Clash:
    return Clash(
        with_=with_,
        kind="solid",
        bbox_nm=(_nm(0), _nm(0), _nm(0), _nm(1), _nm(1), _nm(1)),
        depth_nm=_nm(depth_nm),
        axis="z",
        volume_nm3=volume_nm3,
    )


def _placement(
    *,
    rank: int = 1,
    x_nm: int = 0,
    y_nm: int = 0,
    z_nm: int = 0,
    theta_deg: float = 0.0,
    insertions: tuple[int | None, ...] = (),
    clashes: tuple[Clash, ...] = (),
) -> Placement:
    correspondence = tuple(
        _correspondence(f"D{index}", insertion, hole_index=index + 1)
        for index, insertion in enumerate(insertions)
    )
    return Placement(
        rank=rank,
        x_nm=_nm(x_nm),
        y_nm=_nm(y_nm),
        z_nm=_nm(z_nm),
        theta_deg=theta_deg,
        correspondence=correspondence,
        clashes=clashes,
    )


def _dock(placements: dict[int, tuple[Placement, ...]]) -> DockData:
    return DockData(case=_case(), placements=placements)


def _placement_with_insertions(insertions: list[int | None]) -> DockData:
    return _dock({1: (_placement(insertions=tuple(insertions)),)})


# --------------------------------------------------------------------------
# Seating depth
# --------------------------------------------------------------------------


def test_travel_is_the_least_insertion_over_the_correspondences() -> None:
    """The shallowest part is what stops the board, not the average or the
    deepest -- so a fixture with a distinct minimum (neither the first nor
    the last entry) proves the reduction is really ``min``."""
    data = Seat().apply(_placement_with_insertions([9_000_000, 3_000_000, 7_000_000]))
    assert data.placements[1][0].z_nm == Nanometre(-3_000_000)


def test_a_part_that_passes_fully_does_not_constrain_seating() -> None:
    """``insertion_through`` returns ``None`` for a part the hole admits
    entirely; a ``None`` treated as zero would seat the board on nothing.
    Mixing a ``None`` with a bounded entry proves ``None`` is excluded from
    the minimum rather than winning it."""
    data = Seat().apply(_placement_with_insertions([None, 4_000_000]))
    assert data.placements[1][0].z_nm == Nanometre(-4_000_000)


def test_seating_depth_is_the_panel_surface_when_nothing_bounds_it() -> None:
    """When every correspondence is unbounded, nothing stops the board
    short of the panel surface: ``z_nm = 0``, not a fallback depth and not
    a ``TypeError`` from ``min()`` over an all-``None`` list."""
    data = Seat().apply(_placement_with_insertions([None, None]))
    assert data.placements[1][0].z_nm == Nanometre(0)


def test_a_standoff_does_not_raise_the_board() -> None:
    """Rule 1 stated as a test: a non-panel-reference solid that would foul
    is a clash for a later stage to report, never a seating constraint --
    and it has no representation in ``Placement.correspondence`` at all, so
    the seating minimum here is computed exactly as it is above, from the
    panel-reference correspondences alone."""
    data = Seat().apply(_placement_with_insertions([9_000_000, 3_000_000, 7_000_000]))
    assert data.placements[1][0].z_nm == Nanometre(-3_000_000)


# --------------------------------------------------------------------------
# Ranking: the six-wide key, in isolation
# --------------------------------------------------------------------------


def _placements_differing_only_in_x() -> tuple[Placement, ...]:
    """Already in ascending x_nm order: ``rank_key`` must be a total order
    that agrees with it, which is what ``keys == sorted(keys)`` checks."""
    return (
        _placement(x_nm=10_000_000, y_nm=0, theta_deg=0.0),
        _placement(x_nm=20_000_000, y_nm=0, theta_deg=0.0),
        _placement(x_nm=30_000_000, y_nm=0, theta_deg=0.0),
    )


def test_ranking_is_a_total_order_over_the_whole_key() -> None:
    """Property the spec names. Equal on the first five elements must still
    order, which is what x_nm and y_nm are in the key for."""
    keys = [rank_key(p) for p in _placements_differing_only_in_x()]
    assert len(set(keys)) == len(keys)
    assert keys == sorted(keys)


def _cascade_placements() -> tuple[Placement, ...]:
    """Three placements, all tied on clashes and theta: two also tie on
    x_nm, so ranking must fall through twice -- to x_nm, then to y_nm -- a
    two-level cascade a two-placement fixture cannot exercise."""
    return (
        _placement(theta_deg=0.0, x_nm=100, y_nm=200),
        _placement(theta_deg=0.0, x_nm=100, y_nm=100),
        _placement(theta_deg=0.0, x_nm=50, y_nm=999),
    )


def test_ranking_cascades_through_every_tied_field() -> None:
    ranked = sorted(_cascade_placements(), key=rank_key)
    assert [(int(p.x_nm), int(p.y_nm)) for p in ranked] == [
        (50, 999),
        (100, 100),
        (100, 200),
    ]


def _theta_beats_x_pair() -> tuple[Placement, Placement]:
    """theta and x both differ, arranged so the two fields disagree about
    which placement comes first -- proving theta precedes x in the key."""
    return (
        _placement(theta_deg=10.0, x_nm=1_000),
        _placement(theta_deg=5.0, x_nm=2_000),
    )


def test_theta_outranks_position_in_the_key() -> None:
    """If x_nm were compared before theta, the 1_000-nm placement (theta
    10) would sort first; theta being earlier in the key reverses that."""
    ranked = sorted(_theta_beats_x_pair(), key=rank_key)
    assert [p.theta_deg for p in ranked] == [5.0, 10.0]


def _symmetric_pair() -> tuple[Placement, ...]:
    return (
        _placement(theta_deg=180.0, x_nm=0, y_nm=0),
        _placement(theta_deg=0.0, x_nm=0, y_nm=0),
    )


def test_ties_fall_through_to_the_transform_not_to_a_measured_quantity() -> None:
    """A genuinely symmetric pair must order on theta, which is exact, so
    the order never depends on kernel round-off."""
    ranked = sorted(_symmetric_pair(), key=rank_key)
    assert [round(p.theta_deg, 6) for p in ranked] == [0.0, 180.0]


def _one_clean_one_clashing() -> tuple[Placement, ...]:
    """The clashing placement has the smaller x_nm, so a comparator that
    checked position before clash count would (wrongly) rank it first."""
    return (
        _placement(x_nm=0, clashes=(_clash(volume_nm3=5, depth_nm=5),)),
        _placement(x_nm=1_000_000),
    )


def test_clean_placements_sort_before_clashing_ones() -> None:
    ranked = sorted(_one_clean_one_clashing(), key=rank_key)
    assert ranked[0].clashes == ()


def _count_beats_volume_pair() -> tuple[Placement, Placement]:
    """One clash of huge volume versus two clashes of tiny volume: if
    volume were compared before count, the two-tiny-clash placement (total
    volume 2) would outrank the one-huge-clash placement (volume 1e9)."""
    return (
        _placement(clashes=(_clash(volume_nm3=1_000_000_000),)),
        _placement(clashes=(_clash(volume_nm3=1), _clash(volume_nm3=1))),
    )


def test_clash_count_outranks_clash_volume_in_the_key() -> None:
    ranked = sorted(_count_beats_volume_pair(), key=rank_key)
    assert [len(p.clashes) for p in ranked] == [1, 2]


def _volume_beats_depth_pair() -> tuple[Placement, Placement]:
    """Equal clash count, volumes and depths disagreeing about the winner:
    if depth were compared before volume, the depth-1 placement would win
    even though its volume (2) is larger than the other's (1)."""
    return (
        _placement(clashes=(_clash(volume_nm3=1, depth_nm=1_000_000),)),
        _placement(clashes=(_clash(volume_nm3=2, depth_nm=1),)),
    )


def test_clash_volume_outranks_clash_depth_in_the_key() -> None:
    ranked = sorted(_volume_beats_depth_pair(), key=rank_key)
    assert [c.volume_nm3 for placement in ranked for c in placement.clashes] == [1, 2]


def _volume_reduction_pair() -> tuple[Placement, Placement]:
    """Tied clash count (2 each); volumes arranged so ``sum`` and ``max``
    disagree about which placement ranks first. First: (10, 10) -- sum 20,
    max 10. Second: (15, 1) -- sum 16, max 15. Ascending sum ranks the
    second placement (16) ahead of the first (20); ascending max would rank
    the first (10) ahead of the second (15) instead."""
    return (
        _placement(clashes=(_clash(volume_nm3=10), _clash(volume_nm3=10))),
        _placement(clashes=(_clash(volume_nm3=15), _clash(volume_nm3=1))),
    )


def test_clash_volume_reduces_by_the_total_not_the_largest_single_clash() -> None:
    """Proves the volume field is ``sum``, not ``max``: this fixture's two
    placements order one way under ``sum`` and the other under ``max``, so a
    reduction changed to ``max`` fails here."""
    ranked = sorted(_volume_reduction_pair(), key=rank_key)
    assert [sum(c.volume_nm3 for c in p.clashes) for p in ranked] == [16, 20]


def _depth_reduction_pair() -> tuple[Placement, Placement]:
    """Tied clash count (2 each) and tied total volume (2 each); depths
    arranged so ``max`` and ``min`` disagree about which placement ranks
    first. First: depths (10, 100) -- max 100, min 10. Second: depths
    (50, 60) -- max 60, min 50. Ascending max ranks the second placement
    (60) ahead of the first (100); ascending min would rank the first (10)
    ahead of the second (50) instead."""
    return (
        _placement(
            clashes=(
                _clash(volume_nm3=1, depth_nm=10),
                _clash(volume_nm3=1, depth_nm=100),
            )
        ),
        _placement(
            clashes=(
                _clash(volume_nm3=1, depth_nm=50),
                _clash(volume_nm3=1, depth_nm=60),
            )
        ),
    )


def test_clash_depth_reduces_by_the_greatest_clash_not_the_least() -> None:
    """Proves the depth field is ``max``, not ``min``: this fixture's two
    placements order one way under ``max`` and the other under ``min``, so a
    reduction changed to ``min`` fails here."""
    ranked = sorted(_depth_reduction_pair(), key=rank_key)
    assert [max(int(c.depth_nm) for c in p.clashes) for p in ranked] == [60, 100]


# --------------------------------------------------------------------------
# apply(): ranks are assigned, nothing is filtered, boards are independent
# --------------------------------------------------------------------------


def _two_placements() -> DockData:
    return _dock(
        {
            1: (
                _placement(x_nm=100, insertions=(5_000_000,)),
                _placement(x_nm=50, insertions=(5_000_000,)),
            )
        }
    )


def test_every_distinct_placement_survives_ranking() -> None:
    """Rank is a reported field, not a filter."""
    data = Seat().apply(_two_placements())
    assert len(data.placements[1]) == 2
    assert sorted(p.rank for p in data.placements[1]) == [1, 2]


def test_ranking_is_independent_per_board() -> None:
    """Each board is ranked against the case alone -- one board's positions
    must not influence another board's rank numbers."""
    data = _dock(
        {
            1: (_placement(x_nm=10_000_000), _placement(x_nm=0)),
            2: (_placement(x_nm=999_000_000),),
        }
    )
    result = Seat().apply(data)
    assert [p.rank for p in result.placements[1]] == [1, 2]
    assert result.placements[2][0].rank == 1


# --------------------------------------------------------------------------
# Seat's own contract beyond seating and ranking: Stage protocol, describe(),
# and that apply() does not double-record processing.
# --------------------------------------------------------------------------


def test_seat_satisfies_the_stage_protocol() -> None:
    """Runtime presence check, mirroring Match's own
    ``test_match_satisfies_the_stage_protocol``."""
    stage = Seat()
    assert isinstance(stage, Stage)
    assert isinstance(type(stage).name, str)
    assert type(stage).name


def test_seat_satisfies_stage_dockdata_under_mypy() -> None:
    """A static conformance assignment: ``isinstance`` alone cannot see that
    ``describe()`` returns a ``StageRun`` rather than a ``str`` -- a runtime
    Protocol checks attribute presence, not signatures. mypy checks this
    line; nothing here needs to run for the check to matter."""
    _conforms: Stage[DockData] = Seat()
    assert _conforms is not None


def test_describe_returns_a_stage_run_named_seat() -> None:
    assert Seat().describe() == StageRun("seat")


def test_apply_does_not_record_its_own_processing() -> None:
    """``Pipeline.run`` already appends ``describe()``; ``apply`` recording
    it too would double the entry the moment Seat runs inside a pipeline."""
    data = _dock({1: (_placement(insertions=(1_000_000,)),)})
    result = Seat().apply(data)
    assert result.processing == ()
