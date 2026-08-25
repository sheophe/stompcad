"""What the clearance stage's untouched-frame shortcut is allowed to key on.

Two properties, kept together because the second depends on the first: a
reframe through a value-equal frame returns the very nanometres it was
given -- across every frame a panel reaches, a bound measured below -- so
selecting the shortcut by frame equality rather than object identity can
only skip arithmetic, never change an answer.
"""

from __future__ import annotations

import math

import pytest

from stompdrill.pipeline import CheckCaseClearance
from stompmodel.frames import CoordinateFrame, FaceFrame
from stompmodel.model import EnclosureMatch, ReferenceOutline
from stompmodel.units import Nanometre
from tests.conftest import FakeCase, at, make_data

MM = 1_000_000


def _twin(frame: FaceFrame) -> FaceFrame:
    """A frame equal to ``frame`` in value and distinct in identity."""
    basis = frame.basis
    ox, oy, oz = basis.origin_nm
    return FaceFrame(
        basis=CoordinateFrame(
            origin_nm=(Nanometre(int(ox)), Nanometre(int(oy)), Nanometre(int(oz))),
            u=(basis.u[0], basis.u[1], basis.u[2]),
            v=(basis.v[0], basis.v[1], basis.v[2]),
            w=(basis.w[0], basis.w[1], basis.w[2]),
        )
    )


def _turned(theta: float, origin_nm: tuple[int, int, int]) -> CoordinateFrame:
    """A basis turned off the axes, which the frame validator permits."""
    ox, oy, oz = origin_nm
    return CoordinateFrame(
        origin_nm=(Nanometre(ox), Nanometre(oy), Nanometre(oz)),
        u=(math.cos(theta), math.sin(theta), 0.0),
        v=(-math.sin(theta), math.cos(theta), 0.0),
        w=(0.0, 0.0, 1.0),
    )


#: Frames a reframe must be value-preserving across: the fake model's own
#: face frame, a plain identity basis, and two bases turned off the axes at
#: an offset origin, where the float arithmetic has the most room to drift.
_FRAMES: tuple[CoordinateFrame, ...] = (
    FakeCase.frame.basis,
    CoordinateFrame(
        origin_nm=(Nanometre(0), Nanometre(0), Nanometre(0)),
        u=(1.0, 0.0, 0.0),
        v=(0.0, 1.0, 0.0),
        w=(0.0, 0.0, 1.0),
    ),
    _turned(math.pi / 6, (-56_200_000, 30_250_000, -2_250_000)),
    _turned(-1.234_567, (123_456_789, -987_654_321, 55_555_555)),
)

#: Canonical points, in nanometres, spanning a panel and then some: the
#: origin, both signs, odd values no scaling lands on, and a metre out.
_POINTS: tuple[int, ...] = (
    0,
    1,
    -1,
    7,
    -999_999,
    1_234_567,
    -1_234_567,
    56_200_000,
    -56_200_000,
    112_400_001,
    -112_400_001,
    999_999_999,
    -999_999_999,
)


#: How far a frame's origin may sit from the model origin before a reframe
#: through a twin stops being exact. ``to_model`` adds the point to the
#: origin in millimetres and ``to_canonical`` subtracts it back, so the
#: cancellation costs an ulp of the origin; past this bound that ulp exceeds
#: ``nm_from_mm``'s half-nanometre rounding. A thousand kilometres is far
#: outside anything an enclosure reaches. Measured, not assumed -- see
#: ``test_the_exactness_bound_is_where_it_is_claimed_to_be``.
_EXACT_ORIGIN_LIMIT_NM = 10**15


def test_reframing_through_a_value_equal_frame_is_exactly_value_preserving():
    """Every point comes back as the integer it went in as, not near it.

    This is the fact the shortcut below rests on. It holds within a
    measured regime rather than unconditionally: every frame swept keeps
    its origin inside ``_EXACT_ORIGIN_LIMIT_NM``, which the sweep asserts
    rather than trusts, so the property never claims more than it covers.
    """
    examined = 0
    drifted: list[tuple[int, int, int, int]] = []
    for frame in _FRAMES:
        assert all(abs(int(o)) <= _EXACT_ORIGIN_LIMIT_NM for o in frame.origin_nm)
        twin = _twin(FaceFrame(basis=frame)).basis
        assert twin == frame and twin is not frame
        for x_nm in _POINTS:
            for y_nm in _POINTS:
                got = frame.reframe(Nanometre(x_nm), Nanometre(y_nm), twin)
                examined += 1
                if got != (x_nm, y_nm):
                    drifted.append((x_nm, y_nm, got[0], got[1]))

    assert examined == len(_FRAMES) * len(_POINTS) ** 2
    assert examined >= 500, "the sweep must be large enough to be evidence"
    assert drifted == []


def test_the_drift_sweep_would_notice_a_frame_that_was_not_a_twin():
    """The control for the sweep above: its comparison is able to fail.

    Reframing the same points through a quarter-turned frame must move
    every one of them but the origin, which a rotation about the origin
    fixes. A sweep that could not tell a turned frame from a twin would be
    passing by comparing nothing.
    """
    source = _FRAMES[1]
    turned = _turned(math.pi / 2, (0, 0, 0))

    moved = sum(
        1
        for x_nm in _POINTS
        for y_nm in _POINTS
        if source.reframe(Nanometre(x_nm), Nanometre(y_nm), turned) != (x_nm, y_nm)
    )

    assert moved == len(_POINTS) ** 2 - 1


def _worst_twin_drift_nm(frame: CoordinateFrame) -> int:
    """The largest nanometre a reframe through ``frame``'s twin moves."""
    twin = _twin(FaceFrame(basis=frame)).basis
    return max(
        max(abs(got[0] - x_nm), abs(got[1] - y_nm))
        for x_nm in _POINTS
        for y_nm in _POINTS
        for got in (frame.reframe(Nanometre(x_nm), Nanometre(y_nm), twin),)
    )


def test_the_exactness_bound_is_where_it_is_claimed_to_be():
    """``_EXACT_ORIGIN_LIMIT_NM`` names a measurement, not a hedge.

    A frame origin at the bound reframes exactly and one an order of
    magnitude beyond it does not, so the sweep's qualification is a fact
    about ``CoordinateFrame.reframe`` and the bound is not free to drift
    unnoticed. The shortcut is unharmed either way: it *skips* the
    reframe, so widening it by value can only remove drift, never add any.
    """
    turn = math.pi / 6
    inside = _turned(turn, (_EXACT_ORIGIN_LIMIT_NM,) * 3)
    beyond = _turned(turn, (_EXACT_ORIGIN_LIMIT_NM * 10,) * 3)

    assert _worst_twin_drift_nm(inside) == 0
    assert _worst_twin_drift_nm(beyond) > 0



class TwinFrameCase:
    """A case model whose ``frame`` is computed, as the protocol permits.

    ``CaseModel`` declares ``frame`` a read-only property, so an
    implementation that builds its registration on demand satisfies it. Each
    read returns an equal, distinct object -- the one case object identity
    and value equality disagree about. Clearance rules are delegated to
    ``FakeCase`` so only the frame differs.
    """

    part = FakeCase.part
    face = FakeCase.face
    model_name = FakeCase.model_name
    plate_nm = FakeCase.plate_nm

    def __init__(self, footprint_nm: tuple[Nanometre, Nanometre]) -> None:
        self._rules = FakeCase()
        self.footprint_nm = footprint_nm
        self.play_area_nm = self._rules.play_area_nm
        self.margin_nm = self._rules.margin_nm
        self.seen: list[tuple[Nanometre, Nanometre]] = []

    @property
    def frame(self) -> FaceFrame:
        return _twin(FakeCase.frame)

    def classify(self, x_nm: Nanometre, y_nm: Nanometre, radius_nm: Nanometre):
        self.seen.append((x_nm, y_nm))
        return self._rules.classify(x_nm, y_nm, radius_nm)


#: The footprint every panel below is drawn for, matching the fake model's
#: own so ``_cross_check`` stays quiet and only the frame is under test.
_FOOTPRINT = (Nanometre(112_400_000), Nanometre(60_500_000))


@pytest.fixture
def reframe_spy(monkeypatch):
    """Count every ``CoordinateFrame.reframe`` the stage performs."""
    calls: list[tuple[Nanometre, Nanometre]] = []
    original = CoordinateFrame.reframe

    def counted(self, x_nm, y_nm, target):
        calls.append((x_nm, y_nm))
        return original(self, x_nm, y_nm, target)

    monkeypatch.setattr(CoordinateFrame, "reframe", counted)
    return calls


def _panel(*, width_nm: int, height_nm: int):
    """A one-hole document carrying an identified, non-square enclosure."""
    data = make_data(
        at(3 * MM, -4 * MM, 7 * MM, index=1),
        reference=ReferenceOutline.from_measurement(
            Nanometre(width_nm), Nanometre(height_nm)
        ),
    )
    return data.with_enclosure(
        EnclosureMatch(
            family="Hammond 1590",
            length_nm=Nanometre(max(width_nm, height_nm)),
            width_nm=Nanometre(min(width_nm, height_nm)),
            candidates=(FakeCase.part,),
            selected_part=FakeCase.part,
        )
    )


def test_a_value_equal_but_distinct_frame_takes_the_untouched_path(reframe_spy):
    """An unturned panel skips the reframe even when no object is shared.

    The model rebuilds its frame on every read, so nothing the stage holds
    is the same object as ``model.frame``. Keying the shortcut on identity
    sends this panel through the reframe arithmetic instead.
    """
    model = TwinFrameCase(_FOOTPRINT)

    result = CheckCaseClearance(model).apply(
        _panel(width_nm=112_400_000, height_nm=60_500_000)
    )

    assert model.seen == [(Nanometre(3 * MM), Nanometre(-4 * MM))]
    assert reframe_spy == []
    assert result.case is not None
    assert result.case.frame == FakeCase.frame


def test_a_turned_panel_still_reaches_the_reframe(reframe_spy):
    """The control for the test above: the spy is able to fire.

    A portrait outline against a landscape footprint is the one case that
    must reframe, so a zero count there would be the instrument finding
    nothing rather than the shortcut working.
    """
    model = TwinFrameCase(_FOOTPRINT)

    result = CheckCaseClearance(model).apply(
        _panel(width_nm=60_500_000, height_nm=112_400_000)
    )

    assert len(reframe_spy) == 1
    assert model.seen != [(Nanometre(3 * MM), Nanometre(-4 * MM))]
    assert result.case is not None
    assert result.case.frame != FakeCase.frame


def test_describe_reports_the_play_area_untouched_for_a_value_equal_frame(reframe_spy):
    """The stage's second shortcut keys on the same comparison.

    ``describe()`` restates the play area in the frame ``apply()`` checked.
    For an unturned panel that frame is equal to the model's own, so the
    rectangle must be handed back verbatim and no corner reframed.
    """
    model = TwinFrameCase(_FOOTPRINT)
    stage = CheckCaseClearance(model)
    stage.apply(_panel(width_nm=112_400_000, height_nm=60_500_000))
    reframe_spy.clear()

    run = stage.describe()

    assert reframe_spy == []
    assert dict(run.parameters)["play_area_nm"] == tuple(int(v) for v in model.play_area_nm)


def test_describe_reframes_every_corner_for_a_turned_panel(reframe_spy):
    """The control for the test above: four corners, not zero."""
    model = TwinFrameCase(_FOOTPRINT)
    stage = CheckCaseClearance(model)
    stage.apply(_panel(width_nm=60_500_000, height_nm=112_400_000))
    reframe_spy.clear()

    run = stage.describe()

    assert len(reframe_spy) == 4
    assert dict(run.parameters)["play_area_nm"] != tuple(int(v) for v in model.play_area_nm)
