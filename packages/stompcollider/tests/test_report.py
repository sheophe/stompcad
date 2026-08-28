"""The dock report: ``stompcollider-dock-report`` v1, ``emitters/report.py``.

Fixtures are hand-built -- no kernel, no fixture file -- and chosen to avoid
the task's own named vacuity hazards: an angle whose sixth decimal is
significant (not one that renders identically at three places), a
``case.face`` that is not the value a hard-coded default would pick, at
least two boards so ``unmatched_holes`` reported once can be told apart from
reported per board, and a non-zero ``offset_nm`` on a placement so the
near-miss field is actually exercised.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from stompcollider.emitters.report import ReportEmitter
from stompcollider.model import Board, Clash, Correspondence, DockData, Placement
from stompmodel.diagnostics import Diagnostic
from stompmodel.frames import CoordinateFrame, FaceFrame
from stompmodel.model import CaseFace, CaseRegistration
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


def _case(face: str = "box") -> CaseRegistration:
    # Hazard 2: "box" is the value a hard-coded default would likely pick
    # (it is ``CaseFace``'s first member), so tests that care about this
    # detail pass ``face="lid"`` explicitly.
    return CaseRegistration("1590BB", CaseFace(face), "1590BB.stp", FaceFrame(_identity_frame()))


def _correspondence(
    designator: str = "RV3",
    hole_index: int = 4,
    insertion_nm: int | None = 9_000_000,
    offset_nm: int = 150_000,
) -> Correspondence:
    # Hazard 4: 150_000 nm (0.15 mm) is a non-zero default, so a fixture
    # that never overrides it still exercises the near-miss field the tool
    # exists to report.
    return Correspondence(
        designator=designator,
        hole_index=hole_index,
        hole_xy_nm=(_nm(12_400_000), _nm(30_000_000)),
        insertion_nm=None if insertion_nm is None else _nm(insertion_nm),
        offset_nm=_nm(offset_nm),
    )


def _clash(with_: str = "LID") -> Clash:
    return Clash(
        with_=with_,
        kind="case",
        bbox_nm=(_nm(-4_000_000), _nm(20_000_000), _nm(-2_100_000), _nm(4_000_000), _nm(26_000_000), _nm(0)),
        depth_nm=_nm(2_100_000),
        axis="w",
        volume_nm3=42_000_000_000_000_000_000,
    )


def _placement(
    theta: float = 180.0,
    offset_nm: int = 150_000,
    correspondence: tuple[Correspondence, ...] | None = None,
    clashes: tuple[Clash, ...] = (),
) -> Placement:
    if correspondence is None:
        correspondence = (_correspondence(offset_nm=offset_nm),)
    return Placement(
        rank=1,
        x_nm=_nm(0),
        y_nm=_nm(0),
        z_nm=_nm(-28_085_000),
        theta_deg=theta,
        correspondence=correspondence,
        clashes=clashes,
    )


def _board(ordinal: int = 1, designators: tuple[str, ...] = ("RV3",)) -> Board:
    return Board(
        ordinal=ordinal,
        designators=designators,
        extent_nm=(_nm(106_500_000), _nm(53_750_000), _nm(1_510_000)),
        carrier=_identity_frame(),
        components=(),
        panel_face="-w",
    )


def _data(
    face: str = "box",
    theta: float = 180.0,
    offset_nm: int = 150_000,
) -> DockData:
    board = _board()
    placement = _placement(theta=theta, offset_nm=offset_nm, clashes=(_clash(),))
    return DockData(
        case=_case(face=face),
        boards=(board,),
        holes=(),
        placements={1: (placement,)},
        unmatched_holes=(),
        diagnostics=(
            Diagnostic.warning(
                "unmatched-part", "RV5 has no hole", data=(("designator", "RV5"),)
            ),
        ),
    )


# --------------------------------------------------------------------------
# What the document itself claims, one test per claim
# --------------------------------------------------------------------------


def test_the_header_names_the_format_and_version() -> None:
    document = json.loads(ReportEmitter().emit(_data()))
    assert document["format"] == "stompcollider-dock-report"
    assert document["version"] == 1
    assert document["units"] == "nm"


def test_the_case_face_is_echoed_not_chosen() -> None:
    """Given a drill document cut in the lid, the report must say lid."""
    document = json.loads(ReportEmitter().emit(_data(face="lid")))
    assert document["case"]["face"] == "lid"


def test_the_case_face_echoes_box_too() -> None:
    """The control for the test above: "lid" passing alone would not prove
    the field is echoed rather than always "lid" or always some default."""
    document = json.loads(ReportEmitter().emit(_data(face="box")))
    assert document["case"]["face"] == "box"


def test_angles_carry_exactly_six_decimal_places() -> None:
    """The only float in the document; byte identity depends on this format."""
    payload = ReportEmitter().emit(_data(theta=180.0))
    assert b'"theta_deg": 180.000000' in payload


def test_angles_are_not_truncated_to_three_decimal_places() -> None:
    """Hazard 1's own control: 180.0 renders identically at three and six
    decimal places, so it cannot tell six-decimal formatting from
    three-decimal formatting. This angle's sixth decimal is significant,
    so a formatter using three (or any fewer than six) places fails here."""
    payload = ReportEmitter().emit(_data(theta=142.123456))
    assert b'"theta_deg": 142.123456' in payload
    assert b"142.123" not in payload.replace(b"142.123456", b"")


def test_the_recognition_miss_is_a_field() -> None:
    document = json.loads(ReportEmitter().emit(_data(offset_nm=150_000)))
    assert document["boards"][0]["placements"][0]["correspondence"][0]["offset_nm"] == 150_000


def test_a_full_insertion_serialises_as_null() -> None:
    """A hole that admits the part fully has no depth to state -- a real
    geometric fact, not a missing measurement, so it is JSON ``null`` and
    the key stays present rather than disappearing."""
    correspondence = (_correspondence(insertion_nm=None),)
    placement = _placement(correspondence=correspondence)
    data = DockData(
        case=_case(),
        boards=(_board(),),
        placements={1: (placement,)},
    )
    document = json.loads(ReportEmitter().emit(data))
    entry = document["boards"][0]["placements"][0]["correspondence"][0]
    assert "insertion_nm" in entry
    assert entry["insertion_nm"] is None


def test_a_diagnostic_location_serialises_as_a_pair() -> None:
    """``location_nm`` is always present, ``null`` when a finding is
    panel-wide -- but the not-``None`` branch needs its own test, or an
    implementation that always writes ``null`` (indistinguishable from
    plain omission on every other fixture here) would still pass."""
    located = Diagnostic.warning(
        "unmatched-part",
        "RV5 has no hole",
        location_nm=(_nm(12_400_000), _nm(30_000_000)),
        data=(("designator", "RV5"),),
    )
    data = DockData(case=_case(), boards=(_board(),), diagnostics=(located,))
    document = json.loads(ReportEmitter().emit(data))
    assert document["diagnostics"][0]["location_nm"] == [12_400_000, 30_000_000]


def test_a_panel_wide_diagnostic_location_serialises_as_null() -> None:
    """The control for the test above: a fixture whose only diagnostic
    always has ``location_nm=None`` cannot tell "always null" from
    "echoes what was given"."""
    document = json.loads(ReportEmitter().emit(_data()))
    assert document["diagnostics"][0]["location_nm"] is None


def test_a_diagnostic_datum_that_is_a_pair_serialises_as_a_list() -> None:
    """``wrong-case-model`` carries two footprints as tuples of lengths, and
    JSON has no tuple. A scalar in the same mapping stays a scalar, so this
    fails an implementation that listed every value it was handed."""
    measured = Diagnostic.error(
        "wrong-case-model",
        "the model is not the enclosure the drill document identifies",
        data=(
            ("model", "case.stp"),
            ("enclosure_nm", (_nm(112_400_000), _nm(60_500_000))),
        ),
    )
    data = DockData(case=_case(), boards=(_board(),), diagnostics=(measured,))

    document = json.loads(ReportEmitter().emit(data))

    assert document["diagnostics"][0]["data"] == {
        "model": "case.stp",
        "enclosure_nm": [112_400_000, 60_500_000],
    }


def _placements_out_of_rank_order() -> tuple[Placement, ...]:
    """Two placements for one board, built with rank 2 listed before rank
    1 -- the same "trust the field, not the container order" shape as the
    boards-out-of-order fixture above, but for ``Placement.rank``."""
    correspondence = (_correspondence(designator="RV3", hole_index=4),)
    rank_two = Placement(
        rank=2,
        x_nm=_nm(5_000_000),
        y_nm=_nm(0),
        z_nm=_nm(-28_085_000),
        theta_deg=0.0,
        correspondence=correspondence,
        clashes=(),
    )
    rank_one = Placement(
        rank=1,
        x_nm=_nm(0),
        y_nm=_nm(0),
        z_nm=_nm(-28_085_000),
        theta_deg=0.0,
        correspondence=correspondence,
        clashes=(),
    )
    return (rank_two, rank_one)


def test_placements_are_reported_in_rank_order() -> None:
    """A board with two placements supplied rank-2-then-rank-1 must be
    reported rank 1 first. Every other fixture here has at most one
    placement per board, so this is the only test the rank sort answers
    to; removing ``report.py``'s ``sorted(..., key=lambda p: p.rank)``
    turns this red while leaving the rest of the suite green."""
    data = DockData(
        case=_case(),
        boards=(_board(),),
        placements={1: _placements_out_of_rank_order()},
    )
    document = json.loads(ReportEmitter().emit(data))
    assert [p["rank"] for p in document["boards"][0]["placements"]] == [1, 2]


def _two_boards_sharing_leftovers() -> DockData:
    """Two boards, each covering a disjoint subset of holes, with holes 7
    and 9 covered by neither -- an assembly-level fact, not either board's.
    ``unmatched_holes`` is deliberately given out of ascending order to
    prove the report states the set, not whatever order it arrived in.
    """
    board_a = _board(ordinal=1, designators=("RV3",))
    board_b = _board(ordinal=2, designators=("C1",))
    placement_a = _placement(correspondence=(_correspondence(designator="RV3", hole_index=4),))
    placement_b = _placement(
        correspondence=(_correspondence(designator="C1", hole_index=2, offset_nm=0),)
    )
    return DockData(
        case=_case(),
        boards=(board_a, board_b),
        placements={1: (placement_a,), 2: (placement_b,)},
        unmatched_holes=(9, 7),
    )


def test_unmatched_holes_are_reported_once_across_the_assembly() -> None:
    """Not per board: a hole no board covers is an assembly-level fact."""
    document = json.loads(ReportEmitter().emit(_two_boards_sharing_leftovers()))
    assert document["unmatched_holes"] == [7, 9]
    assert all("unmatched_holes" not in board for board in document["boards"])


def _boards_numbered_out_of_order() -> DockData:
    """Fixture rule: boards are numbered out of tuple order, so an emitter
    recomputing an ordinal from list position fails here."""
    board_two = _board(ordinal=2, designators=("C1",))
    board_one = _board(ordinal=1, designators=("RV3",))
    placement_two = _placement(correspondence=(_correspondence(designator="C1", hole_index=2),))
    placement_one = _placement(correspondence=(_correspondence(designator="RV3", hole_index=4),))
    return DockData(
        case=_case(),
        boards=(board_two, board_one),
        placements={2: (placement_two,), 1: (placement_one,)},
    )


def test_the_emitter_reads_the_ordinals_the_model_states() -> None:
    """Fixture rule: boards are numbered out of tuple order, so an emitter
    recomputing an ordinal from list position fails here."""
    document = json.loads(ReportEmitter().emit(_boards_numbered_out_of_order()))
    assert [b["ordinal"] for b in document["boards"]] == [2, 1]


# --------------------------------------------------------------------------
# Determinism -- ADR-0006 over the report.
# --------------------------------------------------------------------------


def _assembly(shuffled: bool) -> DockData:
    """Two boards, same geometry, two representations of it.

    Board order (a meaningful, already-canonical sequence this emitter only
    echoes) is identical in both calls. What differs is genuinely
    order-free structure: ``unmatched_holes`` -- a set of leftover holes,
    not a ranked list -- and the insertion order of the ``placements``
    mapping, which nothing here ever iterates directly.
    """
    board_a = _board(ordinal=1, designators=("RV3",))
    board_b = _board(ordinal=2, designators=("C1",))
    placement_a = _placement(correspondence=(_correspondence(designator="RV3", hole_index=4),))
    placement_b = _placement(
        correspondence=(_correspondence(designator="C1", hole_index=2, offset_nm=0),)
    )
    unmatched = (9, 7) if not shuffled else (7, 9)
    placements = (
        {1: (placement_a,), 2: (placement_b,)}
        if not shuffled
        else {2: (placement_b,), 1: (placement_a,)}
    )
    return DockData(
        case=_case(),
        boards=(board_a, board_b),
        placements=placements,
        unmatched_holes=unmatched,
    )


def test_two_inputs_of_one_assembly_emit_identical_bytes() -> None:
    """ADR-0006 over the report: no rule may consult input order."""
    assert ReportEmitter().emit(_assembly(False)) == ReportEmitter().emit(_assembly(True))


def test_the_same_data_emits_identical_bytes_across_processes() -> None:
    """Within one process is not enough: hash randomisation only differs
    *between* processes, so a set or dict leaking iteration order into the
    payload could pass a same-process comparison by luck. Shell out twice.
    """
    tests_dir = Path(__file__).resolve().parent
    script = (
        f"import sys; sys.path.insert(0, {str(tests_dir)!r}); "
        "from test_report import _assembly; "
        "from stompcollider.emitters.report import ReportEmitter; "
        "sys.stdout.buffer.write(ReportEmitter().emit(_assembly(False)))"
    )

    first = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, check=True
    ).stdout
    second = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, check=True
    ).stdout
    assert first == second
    assert first == ReportEmitter().emit(_assembly(False))
