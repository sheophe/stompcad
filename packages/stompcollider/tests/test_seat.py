"""Seat: how deep a board goes, and in what order placements are reported.

Fixtures are hand-built, no kernel, no fixture file -- ``Placement`` and
``Clash`` are pure value objects, so the ranking key can be exercised
directly even though no clash detector exists yet. Positions are chosen to
avoid every vacuity hazard the task names -- see the comment above each
fixture group for which hazard it targets.
"""

from __future__ import annotations

from dataclasses import replace

from stompcollider.insert import Insertion
from stompcollider.model import Board, Clash, Correspondence, DockData, Placement
from stompcollider.seat import Seat, rank_key
from stompmodel.diagnostics import Severity
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


#: How far above its board the tip of every hand-built part here stands.
#: Non-zero, and different from every seating below, so an implementation
#: reducing the insertion depth rather than the seating it implies reads a
#: different number rather than the same one.
_TIP = 20_000_000


def _correspondence(designator: str, seat_nm: int | None, hole_index: int) -> Correspondence:
    """One pairing, stated by where it alone would bring the board to rest.

    ``insertion_nm`` is derived rather than given: the two are the same
    fact measured from opposite ends -- a depth from the part's tip, and
    the travel that depth leaves the board -- and a fixture free to state
    them inconsistently would let ``Seat`` read either and look right.
    """
    return Correspondence(
        designator=designator,
        hole_index=hole_index,
        hole_xy_nm=(_nm(0), _nm(0)),
        insertion_nm=None if seat_nm is None else _nm(seat_nm + _TIP),
        offset_nm=_nm(0),
        seat_nm=None if seat_nm is None else _nm(seat_nm),
    )


def _clash(
    bbox_volume_nm3: int = 0,
    depth_nm: int = 0,
    with_: str = "case",
    common_volume_nm3: int | None = None,
    kind: str = "solid",
) -> Clash:
    """One clash. The two volumes agree unless a test sets them apart."""
    return Clash(
        with_=with_,
        kind=kind,
        bbox_nm=(_nm(0), _nm(0), _nm(0), _nm(1), _nm(1), _nm(1)),
        depth_nm=_nm(depth_nm),
        axis="z",
        bbox_volume_nm3=bbox_volume_nm3,
        common_volume_nm3=bbox_volume_nm3 if common_volume_nm3 is None else common_volume_nm3,
    )


def _placement(
    *,
    rank: int = 1,
    x_nm: int = 0,
    y_nm: int = 0,
    z_nm: int = 0,
    theta_deg: float = 0.0,
    seatings: tuple[int | None, ...] = (),
    clashes: tuple[Clash, ...] = (),
) -> Placement:
    correspondence = tuple(
        _correspondence(f"D{index}", seat, hole_index=index + 1)
        for index, seat in enumerate(seatings)
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


def _placement_with_seatings(seatings: list[int | None]) -> DockData:
    return _dock({1: (_placement(seatings=tuple(seatings)),)})


# --------------------------------------------------------------------------
# Seating depth
# --------------------------------------------------------------------------


def test_travel_is_the_least_seating_over_the_correspondences() -> None:
    """The tallest obstruction is what stops the board, not the average or
    the shortest -- so a fixture with a distinct minimum (neither the first
    nor the last entry) proves the reduction is really ``min``."""
    data = Seat().apply(_placement_with_seatings([-3_000_000, -9_000_000, -7_000_000]))
    assert data.placements[1][0].z_nm == Nanometre(-9_000_000)


def test_a_part_that_passes_fully_does_not_constrain_seating() -> None:
    """``insertion_through`` returns ``None`` for a part the hole admits
    entirely, and such a pairing seats the board nowhere; a ``None`` treated
    as zero would seat it on nothing. Mixing a ``None`` with a bounded entry
    proves ``None`` is excluded from the minimum rather than winning it."""
    data = Seat().apply(_placement_with_seatings([None, -4_000_000]))
    assert data.placements[1][0].z_nm == Nanometre(-4_000_000)


def test_seating_depth_is_the_panel_surface_when_nothing_bounds_it() -> None:
    """When every correspondence is unbounded, nothing stops the board
    short of the panel surface: ``z_nm = 0``, not a fallback depth and not
    a ``TypeError`` from ``min()`` over an all-``None`` list."""
    data = Seat().apply(_placement_with_seatings([None, None]))
    assert data.placements[1][0].z_nm == Nanometre(0)


def test_a_standoff_does_not_raise_the_board() -> None:
    """Rule 1 stated as a test: a non-panel-reference solid that would foul
    is a clash for a later stage to report, never a seating constraint --
    and it has no representation in ``Placement.correspondence`` at all, so
    the seating minimum here is computed exactly as it is above, from the
    panel-reference correspondences alone."""
    data = Seat().apply(_placement_with_seatings([-3_000_000, -9_000_000, -7_000_000]))
    assert data.placements[1][0].z_nm == Nanometre(-9_000_000)


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
        _placement(x_nm=0, clashes=(_clash(bbox_volume_nm3=5, depth_nm=5),)),
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
        _placement(clashes=(_clash(bbox_volume_nm3=1_000_000_000),)),
        _placement(clashes=(_clash(bbox_volume_nm3=1), _clash(bbox_volume_nm3=1))),
    )


def test_clash_count_outranks_clash_volume_in_the_key() -> None:
    ranked = sorted(_count_beats_volume_pair(), key=rank_key)
    assert [len(p.clashes) for p in ranked] == [1, 2]


def _volume_beats_depth_pair() -> tuple[Placement, Placement]:
    """Equal clash count, volumes and depths disagreeing about the winner:
    if depth were compared before volume, the depth-1 placement would win
    even though its volume (2) is larger than the other's (1)."""
    return (
        _placement(clashes=(_clash(bbox_volume_nm3=1, depth_nm=1_000_000),)),
        _placement(clashes=(_clash(bbox_volume_nm3=2, depth_nm=1),)),
    )


def test_clash_volume_outranks_clash_depth_in_the_key() -> None:
    ranked = sorted(_volume_beats_depth_pair(), key=rank_key)
    assert [c.bbox_volume_nm3 for placement in ranked for c in placement.clashes] == [1, 2]


def _volume_reduction_pair() -> tuple[Placement, Placement]:
    """Tied clash count (2 each); volumes arranged so ``sum`` and ``max``
    disagree about which placement ranks first. First: (10, 10) -- sum 20,
    max 10. Second: (15, 1) -- sum 16, max 15. Ascending sum ranks the
    second placement (16) ahead of the first (20); ascending max would rank
    the first (10) ahead of the second (15) instead."""
    return (
        _placement(clashes=(_clash(bbox_volume_nm3=10), _clash(bbox_volume_nm3=10))),
        _placement(clashes=(_clash(bbox_volume_nm3=15), _clash(bbox_volume_nm3=1))),
    )


def test_clash_volume_reduces_by_the_total_not_the_largest_single_clash() -> None:
    """Proves the volume field is ``sum``, not ``max``: this fixture's two
    placements order one way under ``sum`` and the other under ``max``, so a
    reduction changed to ``max`` fails here."""
    ranked = sorted(_volume_reduction_pair(), key=rank_key)
    assert [sum(c.bbox_volume_nm3 for c in p.clashes) for p in ranked] == [16, 20]


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
                _clash(bbox_volume_nm3=1, depth_nm=10),
                _clash(bbox_volume_nm3=1, depth_nm=100),
            )
        ),
        _placement(
            clashes=(
                _clash(bbox_volume_nm3=1, depth_nm=50),
                _clash(bbox_volume_nm3=1, depth_nm=60),
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
# Ranking: how far the board actually went in leads the key.
# --------------------------------------------------------------------------


def _shortfall_beats_clashes_pair() -> tuple[Placement, Placement]:
    """One placement 20 mm short of its holes and clean, one 1 mm short and
    clashing.

    A board arrested 20 mm out has its parts nowhere near their holes, and
    it clashes with less of the enclosure precisely because it never got
    into it. A key led by the clash fields rewards exactly that.
    """
    return (
        _placement(z_nm=-30_000_000, seatings=(-10_000_000,)),
        _placement(
            z_nm=-11_000_000,
            seatings=(-10_000_000,),
            clashes=(_clash(bbox_volume_nm3=5_000, depth_nm=5_000),),
        ),
    )


def test_a_placement_that_inserts_further_outranks_one_that_clashes_less() -> None:
    ranked = sorted(_shortfall_beats_clashes_pair(), key=rank_key)

    assert [int(placement.z_nm) for placement in ranked] == [-11_000_000, -30_000_000]


def test_the_clash_fields_still_decide_between_two_equal_shortfalls() -> None:
    """The control: with nothing to choose on insertion the key falls through
    to the clash fields, so the test above is led by the shortfall rather
    than by a key that stopped reading its clashes."""
    pair = (
        _placement(
            z_nm=-11_000_000,
            seatings=(-10_000_000,),
            clashes=(_clash(bbox_volume_nm3=5_000, depth_nm=5_000),),
        ),
        _placement(z_nm=-11_000_000, seatings=(-10_000_000,)),
    )
    ranked = sorted(pair, key=rank_key)

    assert ranked[0].clashes == ()


def test_the_shortfall_is_measured_against_the_seat_that_placements_holes_fix() -> None:
    """Not the travel alone. These two are ranked one way by the shortfall
    and the other by depth of travel, so a key reading ``z_nm`` directly --
    the obvious mistake, since one board's placements usually share a seat
    -- answers the other order."""
    pair = (
        _placement(z_nm=-20_000_000, seatings=(-10_000_000,)),
        _placement(z_nm=-30_000_000, seatings=(-40_000_000,)),
    )
    ranked = sorted(pair, key=rank_key)

    assert [int(placement.z_nm) for placement in ranked] == [-30_000_000, -20_000_000]


def test_a_clash_with_what_closes_over_the_cavity_takes_no_part_in_ranking() -> None:
    """Stage one filters on the enclosure the board is fitted into. A lid
    that will not close is a finding about the design, and never a reason to
    prefer one seating of it to another."""
    fouls_the_lid = _placement(
        x_nm=1, clashes=(_clash(bbox_volume_nm3=9_000, depth_nm=4_000, kind="closure"),)
    )

    assert rank_key(fouls_the_lid) < rank_key(_placement(x_nm=2))


def test_the_same_clash_against_the_cavity_itself_does_rank_it() -> None:
    """The control: one word of the fixture changes, and the same clash
    ranks the placement behind the clean one."""
    fouls_the_box = _placement(
        x_nm=1, clashes=(_clash(bbox_volume_nm3=9_000, depth_nm=4_000, kind="case"),)
    )

    assert rank_key(_placement(x_nm=2)) < rank_key(fouls_the_box)


# --------------------------------------------------------------------------
# apply(): ranks are assigned, nothing is filtered, boards are independent
# --------------------------------------------------------------------------


def _two_placements() -> DockData:
    return _dock(
        {
            1: (
                _placement(x_nm=100, seatings=(-5_000_000,)),
                _placement(x_nm=50, seatings=(-5_000_000,)),
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
    data = _dock({1: (_placement(seatings=(-1_000_000,)),)})
    result = Seat().apply(data)
    assert result.processing == ()


def _box_beats_material_pair() -> tuple[Placement, Placement]:
    """Equal clash count; the boxes and the material they hold disagree.

    The first placement's clash is a thin region inside a large box -- a
    board meeting a board -- and the second's is a small box packed solid.
    A key summing the boxes ranks them one way round and a key summing the
    material the other.
    """
    return (
        _placement(clashes=(_clash(bbox_volume_nm3=1_000, common_volume_nm3=1),)),
        _placement(clashes=(_clash(bbox_volume_nm3=10, common_volume_nm3=9),)),
    )


def test_ranking_reads_the_material_that_clashes_not_the_box_around_it() -> None:
    """Selection between seatings reads the exact volume; depth and direction
    still come from the box. On the tar assembly the box overstates the
    material by a factor of fifty, so the two are not interchangeable."""
    ranked = sorted(_box_beats_material_pair(), key=rank_key)

    assert [c.common_volume_nm3 for p in ranked for c in p.clashes] == [1, 9]


def test_the_box_volumes_alone_would_have_ranked_that_pair_the_other_way() -> None:
    """The control beside it: a key still summing ``bbox_volume_nm3`` passes the
    test above only by accident, and this states there is no accident."""
    ranked = sorted(
        _box_beats_material_pair(),
        key=lambda p: sum(c.bbox_volume_nm3 for c in p.clashes),
    )

    assert [c.common_volume_nm3 for p in ranked for c in p.clashes] == [9, 1]


# --------------------------------------------------------------------------
# The enclosure's own say. A fake ``Cavity`` -- arithmetic, no kernel -- is
# what lets these state the seating rules rather than the geometry: the
# search itself is exercised in ``test_insert.py``, against solids.
# --------------------------------------------------------------------------


class _Stopping:
    """A cavity that answers one fixed insertion, whatever it is asked."""

    def __init__(self, found: Insertion) -> None:
        self.found = found
        self.asked: list[tuple[int, Nanometre]] = []

    def insertion(self, board, placement, basis) -> Insertion:
        self.asked.append((board.ordinal, placement.z_nm))
        return self.found

    def parameters(self) -> tuple[tuple[str, int], ...]:
        return (("seat_pitch_max_nm", 2_000_000), ("seat_pitch_min_nm", 50_000))


def _board(ordinal: int = 1) -> Board:
    return Board(
        ordinal=ordinal,
        designators=("D0", "D1"),
        extent_nm=(_nm(20_000_000), _nm(10_000_000), _nm(1_600_000)),
        carrier=_identity_frame(),
        components=(),
        panel_face="+w",
    )


def _docked(placement: Placement, ordinal: int = 1) -> DockData:
    return DockData(
        case=_case(), boards=(_board(ordinal),), placements={ordinal: (placement,)}
    )


def test_the_cavity_is_asked_about_the_depth_the_holes_fix_not_the_raw_one() -> None:
    """Seating is reduced first, then searched: a cavity handed a placement
    still carrying ``z = 0`` would walk the path toward the wrong seat."""
    cavity = _Stopping(Insertion(_nm(-9_000_000)))
    data = _docked(_placement(z_nm=0, seatings=(-9_000_000, -4_000_000)))

    Seat(cavity).apply(data)

    assert cavity.asked == [(1, _nm(-9_000_000))]


def test_an_enclosure_that_stops_the_board_short_is_what_fixes_its_depth() -> None:
    """The hole geometry says -9 mm; the case says -12 mm, and the case wins.

    Not a correction to yield to but the depth the board actually reaches:
    the shortfall is the finding, and the placement records where the board
    really is so the assembly draws it there.
    """
    cavity = _Stopping(Insertion(_nm(-12_000_000), "RV1", "BOX"))
    data = _docked(_placement(seatings=(-9_000_000, -4_000_000)))

    seated = Seat(cavity).apply(data)

    assert seated.placements[1][0].z_nm == _nm(-12_000_000)


def _paired(designator: str, seat_nm: int, tip_nm: int) -> Correspondence:
    """One pairing with a tip of its own, so two can differ in reach."""
    return Correspondence(
        designator=designator,
        hole_index=1 + int(designator[-1]),
        hole_xy_nm=(_nm(0), _nm(0)),
        insertion_nm=_nm(seat_nm + tip_nm),
        offset_nm=_nm(0),
        seat_nm=_nm(seat_nm),
    )


def test_seated_short_states_the_shortfall_and_the_pairings_it_leaves_unmet() -> None:
    """Every part of the finding the spec names.

    ``D0`` stands 20 mm above the board and still reaches the plate from
    12 mm down; ``D1`` stands 6 mm and no longer does. The long part is the
    control: a rule reporting every pairing of a board that fell short --
    which is all of them, since it rests deeper than any pairing's own
    seating -- would name both and say nothing.
    """
    cavity = _Stopping(Insertion(_nm(-12_000_000), "board:1:D0", "BOX"))
    placement = replace(
        _placement(),
        correspondence=(
            _paired("D0", -9_000_000, 20_000_000),
            _paired("D1", -4_000_000, 6_000_000),
        ),
    )
    data = _docked(placement)

    found = [d for d in Seat(cavity).apply(data).diagnostics if d.code == "seated-short"]

    assert len(found) == 1
    assert found[0].severity is Severity.WARNING
    assert found[0].get("shortfall_nm") == 3_000_000
    assert found[0].get("depth_nm") == -12_000_000
    assert found[0].get("with") == "BOX"
    assert found[0].get("part") == "board:1:D0"
    assert found[0].get("unmet") == ("D1",)


def test_a_board_that_cannot_enter_is_an_error_and_never_a_travel_of_zero() -> None:
    """Two different facts: a board that cannot go in at all, and one that
    seats at the face. The depth recorded stays the one the holes fix, and
    the error is what withholds every artefact."""
    cavity = _Stopping(Insertion(None, "board:1:D0", "BOX"))
    data = _docked(_placement(seatings=(-9_000_000,)))

    seated = Seat(cavity).apply(data)
    found = [d for d in seated.diagnostics if d.code == "cannot-enter"]

    assert [d.severity for d in found] == [Severity.ERROR]
    assert seated.placements[1][0].z_nm == _nm(-9_000_000)


def test_a_board_meeting_what_closes_over_the_cavity_says_the_case_is_shallow() -> None:
    """A lid that will not close is a finding, never a seating removed from
    consideration: the depth is unchanged and the warning states by how much."""
    cavity = _Stopping(Insertion(_nm(-9_000_000), lid_nm=_nm(3_150_000), lid_solid="LID"))
    data = _docked(_placement(seatings=(-9_000_000,)))

    seated = Seat(cavity).apply(data)
    found = [d for d in seated.diagnostics if d.code == "enclosure-too-shallow"]

    assert seated.placements[1][0].z_nm == _nm(-9_000_000)
    assert [d.severity for d in found] == [Severity.WARNING]
    assert found[0].get("reach_nm") == 3_150_000
    assert found[0].get("with") == "LID"


def test_a_board_the_case_carries_past_its_hole_seating_is_not_seated_short() -> None:
    """``seated-short`` is a shortfall, so it needs one.

    The search is what fixes the depth and the hole geometry only bounds
    what is reported against it, so a board the enclosure lets *further* in
    than its own profile predicted is seated, not short -- which is the tar
    footswitch board exactly, whose bush is tangent to its bore and whose
    profile therefore states a seating 11 mm shallower than the plate does.
    """
    cavity = _Stopping(Insertion(_nm(-6_000_000), "board:1:D0", "BOX"))
    data = _docked(_placement(seatings=(-9_000_000,)))

    seated = Seat(cavity).apply(data)

    assert seated.placements[1][0].z_nm == _nm(-6_000_000)
    assert [d.code for d in seated.diagnostics] == []


def test_a_board_that_reaches_its_seat_earns_no_finding_at_all() -> None:
    """The control beside the three above: an unobstructed insertion is
    exactly today's behaviour, so a stage reporting on every placement
    regardless would fail here rather than look thorough."""
    cavity = _Stopping(Insertion(_nm(-9_000_000)))
    data = _docked(_placement(seatings=(-9_000_000,)))

    assert Seat(cavity).apply(data).diagnostics == ()


def test_a_findings_message_names_a_placement_by_its_transform_not_its_rank() -> None:
    """``Clashes`` renumbers every placement once its clashes are known, so a
    rank written here would describe a different seating by the time it is
    read."""
    cavity = _Stopping(Insertion(_nm(-12_000_000), "board:1:D0", "BOX"))
    data = _docked(_placement(x_nm=4_000_000, theta_deg=90.0, seatings=(-9_000_000,)))

    message = Seat(cavity).apply(data).diagnostics[0].message

    assert "x 4.000 y 0.000 mm, theta 90.000 deg" in message
    assert "rank" not in message


def test_a_board_the_stage_was_handed_no_geometry_for_keeps_its_hole_seating() -> None:
    """``Clashes`` refuses the same gap outright; this stage has nothing to
    walk a path with and says so by changing nothing."""
    cavity = _Stopping(Insertion(_nm(-1_000_000), "board:1:D0", "BOX"))
    data = DockData(case=_case(), placements={7: (_placement(seatings=(-9_000_000,)),)})

    seated = Seat(cavity).apply(data)

    assert seated.placements[7][0].z_nm == _nm(-9_000_000)
    assert seated.diagnostics == ()


def test_describe_records_the_two_pitches_the_search_ran_at() -> None:
    cavity = _Stopping(Insertion(_nm(0)))

    assert Seat(cavity).describe() == StageRun(
        "seat", (("seat_pitch_max_nm", 2_000_000), ("seat_pitch_min_nm", 50_000))
    )
