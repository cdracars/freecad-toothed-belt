import math

import pytest

from freecad.toothedbelt import solver
from freecad.toothedbelt.profiles import PROFILES

GT2 = PROFILES["GT2"]


def gt2_fillet(kappa, root_offset=GT2.pld):
    return solver.root_fillet(kappa, GT2.pitch, GT2.tooth_h, root_offset,
                              GT2.tip_r, GT2.flank_r, GT2.flank_offset, GT2.root_r)


class TestLayout:
    def test_closed_exact(self):
        lay = solver.tooth_layout(160.0, 2.0, closed=True)
        assert (lay.count, lay.step, lay.start, lay.pitch_error) == (80, 2.0, 0.0, 0.0)

    def test_closed_rounds_and_reports_error(self):
        lay = solver.tooth_layout(161.3, 2.0, closed=True)
        assert lay.count == 81
        assert lay.pitch_error == pytest.approx(-0.7)
        assert lay.step == pytest.approx(161.3 / 81)

    def test_open_uses_true_pitch_and_centres(self):
        lay = solver.tooth_layout(61.0, 2.0, closed=False)
        assert lay.count == 30
        assert lay.step == 2.0
        assert lay.start == pytest.approx(0.5 * (61.0 - 29 * 2.0))
        # first and last tooth are equally far from the path ends
        last = lay.start + (lay.count - 1) * lay.step
        assert 61.0 - last == pytest.approx(lay.start)

    def test_rejects_non_positive(self):
        with pytest.raises(ValueError):
            solver.tooth_layout(0.0, 2.0, closed=True)


class TestFlankGeometry:
    @pytest.mark.parametrize("name", list(PROFILES))
    def test_tip_tangent_to_flanks_and_reaches_tooth_height(self, name):
        p = PROFILES[name]
        y_ct, y_cf, y_tan = solver.flank_geometry(p.tooth_h, p.tip_r, p.flank_r, p.flank_offset)
        assert y_ct + p.tip_r == pytest.approx(p.tooth_h)
        # tip circle internally tangent to each flank circle
        centre_dist = math.hypot(p.flank_offset, y_ct - y_cf)
        assert centre_dist == pytest.approx(p.flank_r - p.tip_r)
        assert y_cf <= y_tan <= p.tooth_h


class TestRootFillet:
    def test_flat_fillet_tangent_to_root_land_and_flank(self):
        f = gt2_fillet(0.0)
        _, y_cf, _ = solver.flank_geometry(GT2.tooth_h, GT2.tip_r, GT2.flank_r, GT2.flank_offset)
        assert f.y_cr == pytest.approx(GT2.root_r)   # touches y=0
        assert f.y_surf == 0.0 and f.u_surf == pytest.approx(f.u_cr)
        # externally tangent to the +x flank arc, whose centre is at -flank_offset
        d = math.hypot(f.u_cr + GT2.flank_offset, f.y_cr - y_cf)
        assert d == pytest.approx(GT2.flank_r + GT2.root_r)
        assert not f.pinched

    def test_convex_bend_fillet_tangent_to_curved_land(self):
        kappa = -1.0 / 6.37  # teeth on the outside of a 20T pulley
        f = gt2_fillet(kappa)
        r_surf = 6.37 + GT2.pld
        # fillet circle sits outside the land circle centred at (0, -r_surf)
        assert math.hypot(f.u_cr, f.y_cr + r_surf) == pytest.approx(r_surf + GT2.root_r)
        assert math.hypot(f.u_surf, f.y_surf + r_surf) == pytest.approx(r_surf)

    def test_concave_bend_fillet_tangent_to_curved_land(self):
        kappa = 1.0 / 6.37  # teeth facing a 20T pulley
        f = gt2_fillet(kappa)
        r_surf = 6.37 - GT2.pld
        if not f.pinched:
            assert math.hypot(f.u_cr, r_surf - f.y_cr) == pytest.approx(r_surf - GT2.root_r)
            assert math.hypot(f.u_surf, r_surf - f.y_surf) == pytest.approx(r_surf)

    def test_tight_concave_bend_pinches(self):
        f = gt2_fillet(1.0 / 1.2)
        assert f.pinched
        assert 0.0 < f.alpha <= 0.36 * math.pi


class TestCurvatureHelpers:
    def test_side_curvature_matches_circle(self):
        r, ang = 10.0, 0.1
        dx, dy = r * math.sin(ang), r - r * math.cos(ang)
        assert solver.side_curvature(dx, dy) == pytest.approx(1.0 / r)
        assert solver.side_curvature(dx, -dy) == pytest.approx(-1.0 / r)
        assert solver.side_curvature(0.0, 0.0) == 0.0

    def test_quantize(self):
        assert solver.quantize_curvature(0.0004) == 0.0
        assert solver.quantize_curvature(0.1571) == pytest.approx(0.158)
