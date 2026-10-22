"""Pure-math helpers (no FreeCAD imports) so they can be unit-tested anywhere.

Local tooth frame used throughout:
    x  along the belt (tangent to the pitch line)
    y  from the root land at the tooth centre toward the tooth tip
"""

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class ToothLayout:
    count: int
    step: float      # spacing actually used along the path
    start: float     # arc length of the first tooth centre
    pitch_error: float  # path length minus count * pitch (closed paths only)


def tooth_layout(path_length: float, pitch: float, closed: bool) -> ToothLayout:
    """Decide how many teeth fit and where they go.

    Closed loops must hold a whole number of teeth, so the spacing is adjusted
    to the nearest count and the leftover is reported as ``pitch_error``. A
    real belt cannot stretch, so a non-zero error means the sketched loop is
    not a length any stock belt actually has.

    Open paths use the true pitch and centre the teeth on the path.
    """
    if path_length <= 0 or pitch <= 0:
        raise ValueError("path length and pitch must be positive")
    if closed:
        count = max(1, round(path_length / pitch))
        return ToothLayout(count, path_length / count, 0.0, path_length - count * pitch)
    count = max(1, math.floor(path_length / pitch + 1e-9))
    start = 0.5 * (path_length - (count - 1) * pitch)
    return ToothLayout(count, pitch, start, 0.0)


def flank_geometry(tooth_h, tip_r, flank_r, flank_offset):
    """Return (y_tip_centre, y_flank_centre, y_tip_tangent) for the tooth arcs.

    The tip circle is internally tangent to both flank circles.
    """
    y_ct = tooth_h - tip_r
    dr = max(1e-9, flank_r - tip_r)
    dy_cf = math.sqrt(max(0.0, dr * dr - flank_offset * flank_offset))
    y_cf = y_ct - dy_cf
    y_tan = y_ct + tip_r * (dy_cf / dr)
    return y_ct, y_cf, y_tan


def quantize_curvature(kappa: float) -> float:
    """Bucket curvature (1/mm) so identical teeth can be built once and reused."""
    if abs(kappa) < 1e-3:
        return 0.0
    return round(kappa * 500.0) / 500.0


def side_curvature(dx: float, dy: float) -> float:
    """Signed curvature from a neighbour point at local offset (dx, dy).

    Positive means the path bends toward the tooth side (the root land is
    concave there, as when the teeth face a pulley).
    """
    chord_sq = dx * dx + dy * dy
    if chord_sq < 1e-10:
        return 0.0
    return 2.0 * dy / chord_sq


def _intersect_circles_positive_u(x1, y1, r1, x2, y2, r2):
    dx, dy = x2 - x1, y2 - y1
    d = math.hypot(dx, dy)
    if d < 1e-12:
        return None
    a = (r1 * r1 - r2 * r2 + d * d) / (2.0 * d)
    h_sq = r1 * r1 - a * a
    if h_sq < 0.0:
        return None
    h = math.sqrt(h_sq)
    xm, ym = x1 + a * dx / d, y1 + a * dy / d
    rx, ry = -dy * h / d, dx * h / d
    p1, p2 = (xm + rx, ym + ry), (xm - rx, ym - ry)
    cands = sorted((p for p in (p1, p2) if p[0] > 0.0), key=lambda p: p[0])
    if not cands:
        return p1 if p1[0] >= p2[0] else p2
    return cands[0]


@dataclass(frozen=True)
class RootFillet:
    u_cr: float          # fillet circle centre x (positive side)
    y_cr: float          # fillet circle centre y
    u_surf: float        # tangent point on the root land, x
    y_surf: float        # tangent point on the root land, y
    y_flank_tan: float   # tangent point on the flank, y
    pinched: bool        # neighbouring teeth crowd each other (tight concave bend)
    alpha: float         # half-angle to the neighbouring tooth when pinched


def root_fillet(kappa, pitch, tooth_h, root_offset, tip_r, flank_r, flank_offset, root_r):
    """Fillet between the tooth flank and a root land of curvature ``kappa``.

    Ported from the Fusion add-in's ``solve_side_root_fillet``. ``root_offset``
    is the distance from the pitch line to the root land (the PLD for a
    single-sided belt, half the backing for a double-sided one). The original
    always used the PLD here, which is off for double-sided belts.

    Returns the fillet for the +x side; mirror x for the other side.
    """
    _, y_cf, _ = flank_geometry(tooth_h, tip_r, flank_r, flank_offset)
    d_flank = flank_r + root_r

    y_cr_flat = root_r
    u_cr_flat = -flank_offset + math.sqrt(max(1e-12, d_flank * d_flank - (y_cr_flat - y_cf) ** 2))
    pinched = False
    alpha = 0.0

    if abs(kappa) < 1e-5:
        u_cr, y_cr, u_surf, y_surf = u_cr_flat, y_cr_flat, u_cr_flat, 0.0
    elif kappa < 0.0:
        # Root land curves away from the tooth (teeth on the outside of a bend).
        r_path = 1.0 / abs(kappa)
        r_surf = r_path + root_offset
        d_surf = r_surf + root_r
        sol = _intersect_circles_positive_u(-flank_offset, y_cf, d_flank, 0.0, -r_surf, d_surf)
        if sol is not None:
            u_cr, y_cr = sol
            u_surf = u_cr * (r_surf / d_surf)
            y_surf = -r_surf + (y_cr + r_surf) * (r_surf / d_surf)
        else:
            u_cr, y_cr, u_surf, y_surf = u_cr_flat, y_cr_flat, u_cr_flat, 0.0
    else:
        # Root land curves toward the tooth (teeth on the inside of a bend).
        r_path = max(root_offset + 2.2 * root_r, 1.0 / kappa)
        r_surf = max(1.5 * root_r, r_path - root_offset)
        d_surf = max(0.2 * root_r, r_surf - root_r)
        alpha = min(math.pi * 0.36, 0.5 * pitch / r_path)
        sol = _intersect_circles_positive_u(-flank_offset, y_cf, d_flank, 0.0, r_surf, d_surf)
        need_pinch = True
        if sol is not None:
            u_try, y_try = sol
            if u_try <= (r_surf - y_try) * math.tan(alpha):
                u_cr, y_cr = u_try, y_try
                u_surf = u_cr * (r_surf / d_surf)
                y_surf = r_surf - (r_surf - y_cr) * (r_surf / d_surf)
                need_pinch = False
        if need_pinch:
            pinched = True
            dy0 = r_surf - y_cf
            sin_a, cos_a = math.sin(alpha), math.cos(alpha)
            b_q = flank_offset * sin_a - dy0 * cos_a
            c_q = flank_offset * flank_offset + dy0 * dy0 - d_flank * d_flank
            tau = -b_q + math.sqrt(max(0.0, b_q * b_q - c_q))
            u_cr, y_cr = tau * sin_a, r_surf - tau * cos_a
            tau_v = tau + root_r
            u_surf, y_surf = tau_v * sin_a, r_surf - tau_v * cos_a

    vx, vy = u_cr + flank_offset, y_cr - y_cf
    v_len = max(1e-12, math.hypot(vx, vy))
    y_flank_tan = y_cf + flank_r * (vy / v_len)
    return RootFillet(u_cr, y_cr, u_surf, y_surf, y_flank_tan, pinched, alpha)
