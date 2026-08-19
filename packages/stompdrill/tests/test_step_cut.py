"""The STEP emitter's cut, its determinism, and the round trip it survives.

Split from ``test_step_emitter.py``: everything here needs the geometry
kernel and (mostly) a downloaded Hammond model, so the whole module is
gated behind ``--hammond``. ``test_step_emitter.py`` stays runnable without
either, which is the point of its own two OCP-free tests.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import pytest

ocp = pytest.importorskip("OCP", reason="needs stompdrill[step]")

pytestmark = pytest.mark.hammond

MM = 1_000_000


def _model_path():
    """The cached 1590BB, fetched on demand. Skips the test if unobtainable."""
    from tests.hammond import require_model

    return require_model("1590BB")


def _model(face: str = "box"):
    from stompdrill.cad import load_case_model
    from stompdrill.units import Nanometre

    return load_case_model(_model_path(), face=face, margin_nm=Nanometre(1 * MM))


def _emit(*holes, face="box", model=None):
    from stompdrill.emitters.step import StepEmitter, StepOptions
    from tests.conftest import make_data

    return StepEmitter(StepOptions(model=model or _model(face))).emit(make_data(*holes))


def _reload(payload: bytes, tmp_path: Path):
    from stompdrill.cad.step import read_step

    target = tmp_path / "out.stp"
    target.write_bytes(payload)
    return read_step(target)


def _volume(shape) -> float:
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return props.Mass()


def test_the_payload_is_bytes():
    from tests.conftest import at

    assert isinstance(_emit(at(0, 0, 6 * MM, index=1)), bytes)


def test_the_payload_is_a_step_file():
    from tests.conftest import at

    assert _emit(at(0, 0, 6 * MM, index=1)).startswith(b"ISO-10303-21;")


def test_the_output_reloads_as_a_valid_solid(tmp_path):
    from OCP.BRepCheck import BRepCheck_Analyzer

    from tests.conftest import at

    document = _reload(_emit(at(0, 0, 6 * MM, index=1)), tmp_path)

    for solid in document.solids:
        assert BRepCheck_Analyzer(solid.shape).IsValid()


def test_the_assembly_and_its_product_names_survive_the_round_trip(tmp_path):
    from stompdrill.cad.step import read_step
    from tests.conftest import at

    document = _reload(_emit(at(0, 0, 6 * MM, index=1)), tmp_path)
    names = {solid.name.upper() for solid in document.solids}

    # The 1590BB assembly is box, lid, and four instances of one screw.
    assert len(document.solids) == len(read_step(_model_path()).solids)
    assert any("BOX" in name for name in names)
    assert any("LID" in name for name in names)


def test_the_volume_removed_matches_the_holes_drilled(tmp_path):
    """pi r^2 t is an authority no self-consistent bad topology can fake."""
    from stompdrill.cad.step import read_step
    from tests.conftest import at

    before = {s.name: _volume(s.shape) for s in read_step(_model_path()).solids}
    document = _reload(_emit(at(0, 0, 6 * MM, index=1)), tmp_path)
    after = {s.name: _volume(s.shape) for s in document.solids}

    model = _model()
    plate_mm = model.plate_nm / 1_000_000
    expected = math.pi * 3.0**2 * plate_mm
    removed = sum(before.values()) - sum(after.values())

    assert removed == pytest.approx(expected, rel=0.02)


def test_only_the_drilled_side_loses_material(tmp_path):
    """An unbounded cylinder would punch the lid as well."""
    from stompdrill.cad.step import read_step
    from tests.conftest import at

    before = {s.name: _volume(s.shape) for s in read_step(_model_path()).solids}
    after = {s.name: _volume(s.shape)
             for s in _reload(_emit(at(0, 0, 6 * MM, index=1)), tmp_path).solids}

    for name, volume in before.items():
        if "BOX" in name.upper():
            assert after[name] < volume
        else:
            # A STEP write/read round trip re-serialises every coordinate
            # through ASCII text, so an untouched solid's volume survives
            # only to that text precision, not bit-for-bit; the screws are
            # small enough that this shows up as a relative, not absolute,
            # tolerance would need to be loose enough to hide a real cut.
            assert after[name] == pytest.approx(volume, abs=0.05)


def test_two_holes_remove_twice_as_much_as_one(tmp_path):
    from stompdrill.cad.step import read_step
    from tests.conftest import at

    base = sum(_volume(s.shape) for s in read_step(_model_path()).solids)
    one = sum(_volume(s.shape)
              for s in _reload(_emit(at(0, 0, 6 * MM, index=1)), tmp_path).solids)
    two = sum(_volume(s.shape) for s in _reload(
        _emit(at(0, 0, 6 * MM, index=1), at(6 * MM, 0, 6 * MM, index=2)), tmp_path).solids)

    assert (base - two) == pytest.approx(2 * (base - one), rel=0.02)


def test_the_hole_is_cut_where_the_frame_puts_it(tmp_path):
    """An off-centre hole must move the drilled solid's bounding box hole, not mirror.

    A weak first check: an undrilled box also leaves the outer bbox
    unchanged, and this alone cannot tell a correctly placed hole from its
    mirror image. See ``test_the_hole_lands_at_the_canonical_position_not_its_mirror``
    for the assertion that actually pins down *where* the bore is.
    """
    from stompdrill.cad.step import bounding_box_mm, read_step
    from tests.conftest import at

    document = _reload(_emit(at(10 * MM, 0, 6 * MM, index=1)), tmp_path)
    (box,) = [s for s in document.solids if "BOX" in s.name.upper()]

    assert bounding_box_mm(box.shape) == pytest.approx(
        bounding_box_mm([s for s in read_step(_model_path()).solids
                         if "BOX" in s.name.upper()][0].shape), abs=1e-3
    ), "cutting a through-hole must not change the solid's outer extent"


def test_the_hole_lands_at_the_canonical_position_not_its_mirror(tmp_path):
    """The one assertion that actually matters: for a drawing that drills aluminium.

    Emits a hole at canonical ``(+10, 0)`` and probes the reloaded solid,
    at mid-plate depth, at both ``(+10, 0)`` and its mirror ``(-10, 0)``:
    the drilled point must read outside the solid, the untouched mirror
    point inside. Negating both in-plane terms in ``_face_point`` — the
    exact mirror bug this guards against — was confirmed by hand to flip
    both assertions (reported in ``task-12-report.md``); the bounding-box
    check above passes unchanged under that same perturbation.
    """
    from OCP.BRepClass3d import BRepClass3d_SolidClassifier
    from OCP.gp import gp_Pnt
    from OCP.TopAbs import TopAbs_State

    from tests.conftest import at

    model = _model()
    document = _reload(_emit(at(10 * MM, 0, 6 * MM, index=1), model=model), tmp_path)
    (box,) = [s for s in document.solids if "BOX" in s.name.upper()]

    frame = model.frame
    origin = tuple(value / 1_000_000 for value in frame.origin_nm)
    depth_mm = (model.plate_nm / 1_000_000) / 2  # mid-plate: solidly inside real material

    def classify(x_mm: float, y_mm: float):
        point = tuple(
            origin[i] + x_mm * frame.u[i] + y_mm * frame.v[i] - depth_mm * frame.w[i]
            for i in range(3)
        )
        return BRepClass3d_SolidClassifier(box.shape, gp_Pnt(*point), 1e-6).State()

    assert classify(10.0, 0.0) == TopAbs_State.TopAbs_OUT, "the drilled point is still solid"
    assert classify(-10.0, 0.0) == TopAbs_State.TopAbs_IN, "the mirror point was cut instead"


def test_emitting_with_no_holes_leaves_the_model_unchanged(tmp_path):
    from stompdrill.cad.step import read_step

    before = sum(_volume(s.shape) for s in read_step(_model_path()).solids)
    after = sum(_volume(s.shape) for s in _reload(_emit(), tmp_path).solids)

    assert after == pytest.approx(before, rel=1e-6)


def test_a_hole_over_cast_lettering_cuts_cleanly(tmp_path):
    """The three-surface case the bounded-boolean strategy was chosen for.

    ``BB_PROBES["relief"]`` sits on a letter: the drill crosses the outer
    wall, the letter-shaped hole in the floor, the letter body, and exits
    through the letter's own top face at a different level. Nothing else in
    this suite exercises a hole placed over lettering.
    """
    from OCP.BRepCheck import BRepCheck_Analyzer

    from stompdrill.cad.step import read_step
    from tests.conftest import at
    from tests.hammond import BB_PROBES

    x_mm, y_mm = BB_PROBES["relief"]
    hole = at(round(x_mm * MM), round(y_mm * MM), 6 * MM, index=1)
    document = _reload(_emit(hole), tmp_path)

    for solid in document.solids:
        assert BRepCheck_Analyzer(solid.shape).IsValid()

    (box,) = [s for s in document.solids if "BOX" in s.name.upper()]
    before = [s for s in read_step(_model_path()).solids if "BOX" in s.name.upper()][0]
    assert _volume(box.shape) < _volume(before.shape)


def test_cutting_the_lid_face_only_affects_the_lid(tmp_path):
    """Exercises the branch where the first component tried does not match.

    The BOX component is visited before LID in this assembly's own order,
    so cutting ``face="lid"`` is also the only test that walks past a
    keyword mismatch before finding its match.
    """
    from stompdrill.cad.step import read_step
    from tests.conftest import at

    before = {s.name: _volume(s.shape) for s in read_step(_model_path()).solids}
    after = {s.name: _volume(s.shape)
             for s in _reload(_emit(at(0, 0, 6 * MM, index=1), face="lid"), tmp_path).solids}

    for name, volume in before.items():
        if "LID" in name.upper():
            assert after[name] < volume
        else:
            assert after[name] == pytest.approx(volume, abs=0.05)


def test_no_matching_component_is_an_emitter_error():
    """``_label_name`` never matching anything is the same failure a
    renamed or mis-supplied model would produce — worth a named diagnostic,
    not a silent no-op."""
    from stompdrill.emitters import step as step_module
    from stompdrill.errors import EmitterError
    from tests.conftest import at, make_data

    def never_named(label: object) -> str:
        return ""

    model = _model()
    original = step_module._label_name
    step_module._label_name = never_named
    try:
        with pytest.raises(EmitterError, match="no component named"):
            step_module.cut_shape(model, make_data(at(0, 0, 6 * MM, index=1)))
    finally:
        step_module._label_name = original


def test_a_boolean_cut_that_reports_failure_is_an_emitter_error(monkeypatch):
    """``IsDone() is False`` is not observed on any cached model; forced here."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut

    from stompdrill.emitters import step as step_module
    from stompdrill.errors import EmitterError
    from tests.conftest import at, make_data

    monkeypatch.setattr(BRepAlgoAPI_Cut, "IsDone", lambda self: False)

    with pytest.raises(EmitterError, match="boolean cut failed"):
        step_module.cut_shape(_model(), make_data(at(0, 0, 6 * MM, index=1)))


def test_five_emits_in_one_process_are_byte_identical():
    """OCC's process-global product-version and NAUO-id counters must not
    leak into the payload: this is the invariant Task 13 depends on."""
    from tests.conftest import at

    model = _model()
    hole = at(0, 0, 6 * MM, index=1)

    payloads = [_emit(hole, model=model) for _ in range(5)]

    assert len(set(payloads)) == 1


def test_emitting_twice_from_one_model_returns_the_same_bytes():
    """``emit`` must not leave the supplied model mutated: a second call on
    the same instance is the test that would catch it, since ``_emit()``'s
    helper reloads a fresh model from disk every other test in this file."""
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    from tests.conftest import at

    model = _model()
    hole = at(0, 0, 6 * MM, index=1)

    first = _emit(hole, model=model)
    second = _emit(hole, model=model)

    assert first == second

    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(model.target_shape, props)
    assert props.Mass() == pytest.approx(52352.83977753624, rel=1e-9)


def test_emitting_is_silent_on_stdout(capfd):
    """OCC's C++ progress banners bypass Python-level capture; only an
    OS-file-descriptor check proves they are actually suppressed."""
    from tests.conftest import at

    capfd.readouterr()
    _emit(at(0, 0, 6 * MM, index=1))
    captured = capfd.readouterr()

    assert captured.out == ""


def test_the_same_input_gives_the_same_bytes_across_fresh_processes(tmp_path):
    """A clock reading in the header only shows up between processes."""
    import subprocess
    import sys
    import textwrap

    model_path = _model_path()
    src_path = Path(__file__).resolve().parents[1] / "src"
    script = textwrap.dedent(
        f"""
        import sys
        sys.path.insert(0, {str(src_path)!r})
        from pathlib import Path
        from stompdrill.cad import load_case_model
        from stompdrill.emitters.step import StepEmitter, StepOptions
        from stompdrill.model import DrillData, Hole
        from stompdrill.units import Nanometre

        model = load_case_model(Path({str(model_path)!r}), face="box",
                                 margin_nm=Nanometre(1_000_000))
        hole = Hole.from_measurement(Nanometre(0), Nanometre(0),
                                     Nanometre(6_000_000)).with_number(1)
        payload = StepEmitter(StepOptions(model=model)).emit(DrillData(holes=(hole,)))
        sys.stdout.buffer.write(payload)
        """
    )
    runs = [
        subprocess.run([sys.executable, "-c", script], capture_output=True, check=True).stdout
        for _ in range(2)
    ]

    assert runs[0] == runs[1]


def test_the_emitted_timestamp_is_copied_from_the_source_model():
    """The contract, asserted directly. A year heuristic would depend on today.

    OCC's own writer emits ``FILE_NAME`` with no ``/* time_stamp */`` field
    comment — that style belongs to the *source* Hammond file (ST-Developer
    output), not to what this emitter writes — so the stamp is read out by
    position, the second quoted string in ``FILE_NAME(...)``, not by name.
    """
    from stompdrill.cad.step import source_timestamp
    from tests.conftest import at

    payload = _emit(at(0, 0, 6 * MM, index=1)).decode("latin-1")
    stamp = payload.split("FILE_NAME(")[1].split("'")[3]

    assert stamp == source_timestamp(_model_path())


def test_tuple_order_does_not_reach_the_output():
    """ADR-0006: no rule may consult input order, kernel included."""
    from tests.conftest import at

    a = at(0, 0, 6 * MM, index=1)
    b = at(8 * MM, 0, 6 * MM, index=2)

    assert _emit(a, b) == _emit(b, a)


def test_hole_numbering_and_not_position_orders_the_cut():
    """Identical geometry numbered differently still cuts the same solid."""
    from tests.conftest import at

    forward = _emit(at(0, 0, 6 * MM, index=1), at(8 * MM, 0, 6 * MM, index=2))
    swapped = _emit(at(0, 0, 6 * MM, index=2), at(8 * MM, 0, 6 * MM, index=1))

    assert forward == swapped


def _cylinder_centres(compound) -> list[tuple[float, float, float]]:
    """Each child's centre of mass, in the compound's own iteration order."""
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.TopoDS import TopoDS_Iterator

    centres = []
    child = TopoDS_Iterator(compound)
    while child.More():
        props = GProp_GProps()
        BRepGProp.VolumeProperties_s(child.Value(), props)
        point = props.CentreOfMass()
        centres.append((round(point.X(), 3), round(point.Y(), 3), round(point.Z(), 3)))
        child.Next()
    return centres


def test_drill_compound_builds_children_in_index_order_not_tuple_order():
    """Directly on ``_drill_compound``, not the byte-level emit.

    Colour re-slotting makes the emitted bytes insensitive to compound
    child order, so a byte comparison alone cannot prove this sort does
    anything; only a probe on the compound itself can. Without the sort,
    the second assertion's child order reverses.
    """
    from stompdrill.emitters import step as step_module
    from tests.conftest import at, make_data

    model = _model()
    a = at(0, 0, 6 * MM, index=1)
    b = at(8 * MM, 0, 6 * MM, index=2)

    forward = _cylinder_centres(step_module._drill_compound(model, make_data(a, b)))
    backward = _cylinder_centres(step_module._drill_compound(model, make_data(b, a)))

    assert forward == [(0.0, -28.875, -0.0), (8.0, -28.875, -0.0)]
    assert forward == backward


def test_a_colour_chain_regex_that_stops_matching_raises_instead_of_passing_silently(monkeypatch):
    """A ``_COLOUR_CHAIN`` that no longer matches must not pass silently.

    Zero chains matched against a coloured document is exactly what a
    future OpenCASCADE upgrade reshaping this entity chain would produce;
    without the count check this looks like "nothing to reorder" and every
    other test in this module still passes. ``monkeypatch`` restores
    ``_COLOUR_CHAIN`` afterwards, so this cannot leak into another test.
    """
    import re

    from stompdrill.emitters import step as step_module
    from stompdrill.errors import EmitterError
    from tests.conftest import at

    broken = re.compile(
        re.sub(rb"STYLED_ITEM", rb"STYLED_ITEM_ZZZ", step_module._COLOUR_CHAIN.pattern),
        step_module._COLOUR_CHAIN.flags,
    )
    monkeypatch.setattr(step_module, "_COLOUR_CHAIN", broken)

    with pytest.raises(EmitterError, match=r"_COLOUR_CHAIN.*likely needs updating"):
        _emit(at(0, 0, 6 * MM, index=1))


def test_the_wrapper_products_name_is_the_one_the_writer_set():
    """The writer's product name and the two patterns that erase its counter
    must name one thing.

    They are three separate uses of ``_PRODUCT_NAME``. Spelled out rather
    than read from it, a rename could set one name and normalise to another:
    every determinism test still passes, because both are stable within a
    run, and the artefact quietly carries two names for one wrapper. This
    asserts the name that reaches the file, which is the only place the
    disagreement is visible.
    """
    from stompdrill.emitters.step import _PRODUCT_NAME
    from tests.conftest import at

    payload = _emit(at(0, 0, 6 * MM, index=1))

    wrapper = f"PRODUCT('{_PRODUCT_NAME}'".encode()
    assert wrapper in payload
    # The counter the translator appends must be gone, not merely stable.
    assert re.search(rb"'" + _PRODUCT_NAME.encode() + rb" \d+\.\d+'", payload) is None


def _colours_by_product(document) -> dict:
    """Every coloured product name in a document, deduplicated by referred label."""
    from OCP.Quantity import Quantity_Color
    from OCP.TDataStd import TDataStd_Name
    from OCP.TDF import TDF_Label, TDF_LabelSequence
    from OCP.XCAFDoc import XCAFDoc_ColorType, XCAFDoc_DocumentTool, XCAFDoc_ShapeTool

    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(document.Main())
    color_tool = XCAFDoc_DocumentTool.ColorTool_s(document.Main())

    def name_of(label):
        holder = TDataStd_Name()
        if label.FindAttribute(TDataStd_Name.GetID_s(), holder):
            return str(holder.Get().ToExtString())
        return ""

    def leaves(label, out):
        if XCAFDoc_ShapeTool.IsAssembly_s(label):
            children = TDF_LabelSequence()
            XCAFDoc_ShapeTool.GetComponents_s(label, children)
            for index in range(1, children.Length() + 1):
                leaves(children.Value(index), out)
        else:
            out.append(label)

    free = TDF_LabelSequence()
    shape_tool.GetFreeShapes(free)
    components: list = []
    for index in range(1, free.Length() + 1):
        leaves(free.Value(index), components)

    colours: dict = {}
    for component in components:
        referred = TDF_Label()
        target = referred if XCAFDoc_ShapeTool.GetReferredShape_s(component, referred) else component
        name = name_of(target)
        if name in colours:
            continue
        colour = Quantity_Color()
        has = color_tool.GetColor(
            XCAFDoc_ShapeTool.GetShape_s(target), XCAFDoc_ColorType.XCAFDoc_ColorSurf, colour
        )
        if has:
            colours[name] = (round(colour.Red(), 2), round(colour.Green(), 2), round(colour.Blue(), 2))
    return colours


def test_the_drilled_solids_own_colour_does_not_survive_a_cut(tmp_path):
    """A known OpenCASCADE writer limitation, documented rather than hidden.

    Re-establishing ``XCAFDoc_ColorTool``'s assignment on the label
    ``SetShape`` replaced does not make ``STEPCAFControl_Writer`` serialise
    it (tried at solid, component and per-face granularity). The untouched
    LID and SCREW keep their exact source colours; the drilled BOX's does
    not survive, which is why ``_count_colour_assignments`` excludes the
    label ``cut_shape`` touched rather than expecting the full source count.
    """
    from stompdrill.cad.step import read_step
    from tests.conftest import at

    source = _colours_by_product(read_step(_model_path()).document)
    result = _reload(_emit(at(0, 0, 6 * MM, index=1)), tmp_path)
    written = _colours_by_product(result.document)

    assert written["1590BB-BBS-C LID"] == source["1590BB-BBS-C LID"]
    assert written["SC530 (screw #6-32X 1_2'' FH)"] == source["SC530 (screw #6-32X 1_2'' FH)"]
    assert "1590BB BOX" not in written


def test_two_emissions_describe_the_same_model(tmp_path):
    """Byte identity is the enforcement mechanism; this is what it proxies for.

    The guarantee is a geometrically and visually identical model, not
    identical bytes for their own sake — bytes are cheap and total to
    check but pinned to a kernel-internal layout this codebase does not
    control. Compares two processes' emissions by product names, per-solid
    volume and bounding box, and colour-to-solid mapping as a set: a
    reordering that leaves the model unchanged still passes, a colour on
    the wrong part or missing would not.
    """
    import subprocess
    import sys
    import textwrap

    from stompdrill.cad.step import bounding_box_mm, read_step

    model_path = _model_path()
    src_path = Path(__file__).resolve().parents[1] / "src"
    script = textwrap.dedent(
        f"""
        import sys
        sys.path.insert(0, {str(src_path)!r})
        from pathlib import Path
        from stompdrill.cad import load_case_model
        from stompdrill.emitters.step import StepEmitter, StepOptions
        from stompdrill.model import DrillData, Hole
        from stompdrill.units import Nanometre

        model = load_case_model(Path({str(model_path)!r}), face="box",
                                 margin_nm=Nanometre(1_000_000))
        hole = Hole.from_measurement(Nanometre(0), Nanometre(0),
                                     Nanometre(6_000_000)).with_number(1)
        payload = StepEmitter(StepOptions(model=model)).emit(DrillData(holes=(hole,)))
        sys.stdout.buffer.write(payload)
        """
    )
    results = []
    for index in range(2):
        payload = subprocess.run(
            [sys.executable, "-c", script], capture_output=True, check=True
        ).stdout
        target = tmp_path / f"out{index}.stp"
        target.write_bytes(payload)
        results.append(read_step(target))

    first, second = results
    first_names = {solid.name for solid in first.solids}
    second_names = {solid.name for solid in second.solids}
    assert first_names == second_names

    for name in first_names:
        one = next(s for s in first.solids if s.name == name)
        two = next(s for s in second.solids if s.name == name)
        # Ø6 mm through a 2.25 mm plate is 63.6 mm^3; a missing hole would
        # show up as a difference two orders of magnitude past this margin.
        assert _volume(one.shape) == pytest.approx(_volume(two.shape), abs=0.1)
        assert bounding_box_mm(one.shape) == pytest.approx(bounding_box_mm(two.shape), abs=1e-3)

    first_colours = set(_colours_by_product(first.document).items())
    second_colours = set(_colours_by_product(second.document).items())
    assert first_colours == second_colours
