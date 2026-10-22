"""End-to-end tests against real FreeCAD (skipped when FreeCAD is not importable)."""

import math
import os

import pytest

FreeCAD = pytest.importorskip("FreeCAD")
Part = pytest.importorskip("Part")
pytest.importorskip("Sketcher")

from freecad.toothedbelt import feature, geometry
from freecad.toothedbelt.profiles import PROFILES

V = FreeCAD.Vector
GT2 = PROFILES["GT2"]
R20 = 20 * 2.0 / math.pi / 2  # 20T GT2 pitch radius


@pytest.fixture
def doc():
    d = FreeCAD.newDocument("BeltTest")
    name = d.Name
    yield d
    if name in FreeCAD.listDocuments():
        FreeCAD.closeDocument(name)


def stadium_sketch(doc, r=R20, centre=60.0, placement=None, name="Path"):
    """Two equal pulleys' pitch circles joined by straight runs."""
    sk = doc.addObject("Sketcher::SketchObject", name)
    if placement is not None:
        sk.Placement = placement
    sk.addGeometry(Part.LineSegment(V(0, r, 0), V(centre, r, 0)))
    sk.addGeometry(Part.ArcOfCircle(Part.Circle(V(centre, 0, 0), V(0, 0, 1), r), -math.pi / 2, math.pi / 2))
    sk.addGeometry(Part.LineSegment(V(centre, -r, 0), V(0, -r, 0)))
    sk.addGeometry(Part.ArcOfCircle(Part.Circle(V(0, 0, 0), V(0, 0, 1), r), math.pi / 2, 3 * math.pi / 2))
    doc.recompute()
    return sk


def belt_ok(obj):
    shape = obj.Shape
    assert not shape.isNull()
    assert shape.isValid()
    assert len(shape.Solids) == 1
    return shape


def test_two_pulley_loop_teeth_inside(doc):
    sk = stadium_sketch(doc)
    belt = feature.make_belt(sk, doc=doc)
    doc.recompute()
    shape = belt_ok(belt)
    assert belt.ToothCount == 80
    assert belt.PathLength.Value == pytest.approx(160.0, abs=1e-6)
    assert belt.PitchError.Value == pytest.approx(0.0, abs=1e-6)
    bb = shape.BoundBox
    # Teeth inside: the outer extent is the back face, h_b - PLD beyond the pitch line.
    assert bb.YMax == pytest.approx(R20 + GT2.backside_offset, abs=1e-3)
    assert bb.ZLength == pytest.approx(6.0, abs=1e-6)
    assert bb.ZMin == pytest.approx(-3.0, abs=1e-6)  # symmetric by default


def test_teeth_outside_extent(doc):
    belt = feature.make_belt(stadium_sketch(doc), teeth_side="Outside", doc=doc)
    doc.recompute()
    bb = belt_ok(belt).BoundBox
    assert bb.YMax == pytest.approx(R20 + GT2.pld + GT2.tooth_h, abs=1e-3)


def test_double_sided_extent(doc):
    belt = feature.make_belt(stadium_sketch(doc), teeth_side="Both", doc=doc)
    doc.recompute()
    bb = belt_ok(belt).BoundBox
    assert bb.YMax == pytest.approx(R20 + 0.5 * GT2.backing_h + GT2.tooth_h, abs=1e-3)


def test_volume_close_to_ideal(doc):
    """Backing + teeth area x width; teeth on a straight run are an exact reference."""
    belt = feature.make_belt(stadium_sketch(doc), doc=doc, root_fillets=False)
    doc.recompute()
    vol = belt_ok(belt).Volume
    backing = 160.0 * GT2.backing_h * 6.0
    assert backing < vol < backing * 1.8


@pytest.mark.parametrize("profile", list(PROFILES))
def test_all_profiles_build(doc, profile):
    p = PROFILES[profile]
    r = 24 * p.pitch / math.pi / 2  # 24T pulleys
    belt = feature.make_belt(stadium_sketch(doc, r=r, centre=25 * p.pitch), profile=profile, doc=doc)
    doc.recompute()
    belt_ok(belt)
    assert belt.ToothCount == 24 + 50


def test_pitch_error_reported(doc):
    belt = feature.make_belt(stadium_sketch(doc, centre=60.35), doc=doc)
    doc.recompute()
    belt_ok(belt)
    assert belt.ToothCount == 80
    assert belt.PitchError.Value == pytest.approx(0.7, abs=1e-6)


def test_rebuilds_when_sketch_changes(doc):
    sk = stadium_sketch(doc)
    belt = feature.make_belt(sk, doc=doc)
    doc.recompute()
    assert belt.ToothCount == 80
    doc.removeObject(sk.Name)
    sk2 = stadium_sketch(doc, centre=80.0, name="Path2")
    belt.Path = sk2
    doc.recompute()
    assert belt.ToothCount == 100

    # Editing the existing sketch's geometry also triggers a rebuild.
    sk2.deleteAllGeometry()
    sk2.addGeometry(Part.LineSegment(V(0, R20, 0), V(90.0, R20, 0)))
    sk2.addGeometry(Part.ArcOfCircle(Part.Circle(V(90.0, 0, 0), V(0, 0, 1), R20), -math.pi / 2, math.pi / 2))
    sk2.addGeometry(Part.LineSegment(V(90.0, -R20, 0), V(0, -R20, 0)))
    sk2.addGeometry(Part.ArcOfCircle(Part.Circle(V(0, 0, 0), V(0, 0, 1), R20), math.pi / 2, 3 * math.pi / 2))
    doc.recompute()
    assert belt.ToothCount == 110


def test_width_expression(doc):
    belt = feature.make_belt(stadium_sketch(doc), doc=doc, symmetric=False)
    belt.setExpression("Width", "2 * 5 mm")
    doc.recompute()
    bb = belt_ok(belt).BoundBox
    assert bb.ZMin == pytest.approx(0.0, abs=1e-6)
    assert bb.ZMax == pytest.approx(10.0, abs=1e-6)


def test_sketch_in_other_plane(doc):
    pl = FreeCAD.Placement(V(0, 5, 0), FreeCAD.Rotation(V(1, 0, 0), 90))  # XZ plane
    belt = feature.make_belt(stadium_sketch(doc, placement=pl), doc=doc)
    doc.recompute()
    bb = belt_ok(belt).BoundBox
    assert bb.YLength == pytest.approx(6.0, abs=1e-6)
    assert bb.YMin == pytest.approx(2.0, abs=1e-6)


def test_open_path(doc):
    sk = doc.addObject("Sketcher::SketchObject", "Open")
    sk.addGeometry(Part.LineSegment(V(0, 0, 0), V(30, 0, 0)))
    sk.addGeometry(Part.ArcOfCircle(Part.Circle(V(30, 10, 0), V(0, 0, 1), 10), -math.pi / 2, math.pi / 2))
    doc.recompute()
    left = feature.make_belt(sk, doc=doc, name="Left")
    right = feature.make_belt(sk, teeth_side="Outside", doc=doc, name="Right")
    doc.recompute()
    belt_ok(left)
    belt_ok(right)
    assert left.ToothCount == right.ToothCount == math.floor((30 + math.pi * 10) / 2.0)
    # The straight run (y=0) is the lowest part. Inside = left of travel (+y), so
    # only the backing sits below it; Outside puts the teeth below it.
    assert left.Shape.BoundBox.YMin == pytest.approx(-GT2.backside_offset, abs=1e-3)
    assert right.Shape.BoundBox.YMin == pytest.approx(-(GT2.pld + GT2.tooth_h), abs=1e-3)


def test_spline_loop(doc):
    pts = [V(20 * math.cos(a), 12 * math.sin(a) + 3 * math.sin(3 * a), 0)
           for a in [i * 2 * math.pi / 12 for i in range(12)]]
    bs = Part.BSplineCurve()
    bs.interpolate(pts, PeriodicFlag=True)
    sk = doc.addObject("Sketcher::SketchObject", "Spline")
    sk.addGeometry(bs)
    doc.recompute()
    belt = feature.make_belt(sk, doc=doc)
    doc.recompute()
    belt_ok(belt)
    assert belt.ToothCount == round(belt.PathLength.Value / 2.0)


def test_bend_too_tight_fails_cleanly(doc):
    sk = doc.addObject("Sketcher::SketchObject", "Tiny")
    sk.addGeometry(Part.Circle(V(0, 0, 0), V(0, 0, 1), 0.2))
    doc.recompute()
    belt = feature.make_belt(sk, doc=doc)
    doc.recompute()
    assert "Invalid" in belt.State or "Error" in str(belt.State) or belt.Shape.isNull()


def test_save_and_reload(doc, tmp_path):
    belt = feature.make_belt(stadium_sketch(doc), profile="HTD 5M", doc=doc)
    doc.recompute()
    path = os.path.join(str(tmp_path), "belt.FCStd")
    doc.saveAs(path)
    belt_name = belt.Name
    FreeCAD.closeDocument(doc.Name)

    d2 = FreeCAD.openDocument(path)
    try:
        b2 = d2.getObject(belt_name)
        assert isinstance(b2.Proxy, feature.ToothedBelt)
        assert b2.Profile == "HTD 5M"
        b2.touch()
        d2.recompute()
        belt_ok(b2)
        assert b2.ToothCount == round(160.0 / 5.0)
    finally:
        FreeCAD.closeDocument(d2.Name)


def test_build_belt_rejects_bad_input():
    wire = Part.Wire(Part.makeCircle(10))
    with pytest.raises(geometry.BeltError):
        geometry.build_belt(wire, V(0, 0, 1), profile="T5")
    with pytest.raises(geometry.BeltError):
        geometry.build_belt(wire, V(0, 0, 1), width=0)
