"""Build a toothed belt solid from a planar pitch-line wire.

Everything is built in 2D (faces in the path plane) and extruded once at the
end: the backing is an exact offset band of the pitch line, and each tooth is a
2D profile placed tangent to the path. That is simpler, exact on arcs and
splines, and faster than the original's per-tooth 3D booleans.
"""

import math
from dataclasses import dataclass

import FreeCAD as App
import Part

from . import solver
from .profiles import PROFILES, BeltProfile

V = App.Vector

SIDES = ("Inside", "Outside", "Both")


class BeltError(Exception):
    """Raised for user-fixable problems (bad path, bend too tight, ...)."""


@dataclass
class BeltResult:
    shape: Part.Shape
    tooth_count: int
    path_length: float
    pitch_error: float
    closed: bool


# --------------------------------------------------------------------------
# Path walking
# --------------------------------------------------------------------------

class PathWalker:
    """Arc-length evaluation of a connected wire, independent of edge orientation."""

    def __init__(self, wire: Part.Wire):
        edges = wire.OrderedEdges
        if not edges:
            raise BeltError("path has no edges")
        self.segments = []
        prev_end = None
        for i, edge in enumerate(edges):
            a, b = edge.FirstParameter, edge.LastParameter
            ps, pe = edge.valueAt(a), edge.valueAt(b)
            if prev_end is not None:
                reverse = (pe - prev_end).Length < (ps - prev_end).Length
            elif len(edges) > 1:
                nxt = edges[1]
                n_ends = (nxt.valueAt(nxt.FirstParameter), nxt.valueAt(nxt.LastParameter))
                reverse = min((ps - q).Length for q in n_ends) < min((pe - q).Length for q in n_ends)
            else:
                reverse = False
            self.segments.append((edge, reverse, edge.Length))
            prev_end = ps if reverse else pe
        self.length = sum(s[2] for s in self.segments)
        self.closed = wire.isClosed()

    def at(self, s: float):
        """Point and unit tangent at arc length ``s`` along the path."""
        if self.closed:
            s %= self.length
        else:
            s = min(max(s, 0.0), self.length)
        acc = 0.0
        last = len(self.segments) - 1
        for i, (edge, reverse, seg_len) in enumerate(self.segments):
            if s <= acc + seg_len or i == last:
                local = min(max(s - acc, 0.0), seg_len)
                dist = seg_len - local if reverse else local
                prm = edge.getParameterByLength(dist)
                pt = edge.valueAt(prm)
                tan = edge.derivative1At(prm)
                # Guard against edges whose derivative ignores orientation.
                a, b = edge.FirstParameter, edge.LastParameter
                h = (b - a) * 1e-4
                fd = edge.valueAt(min(prm + h, b)) - edge.valueAt(max(prm - h, a))
                if tan.dot(fd) < 0:
                    tan = -tan
                if reverse:
                    tan = -tan
                if tan.Length < 1e-12:
                    tan = fd if not reverse else -fd
                tan.normalize()
                return pt, tan
            acc += seg_len
        raise AssertionError("unreachable")


def path_normal(wire: Part.Wire, source_obj=None) -> App.Vector:
    """Plane normal for the path: the sketch's Z axis when available."""
    if source_obj is not None and source_obj.isDerivedFrom("Sketcher::SketchObject"):
        n = source_obj.Placement.Rotation.multVec(V(0, 0, 1))
    else:
        plane = wire.findPlane()
        if plane is None:
            raise BeltError("path is not planar (or is a single straight line); use a sketch")
        n = V(plane.Axis)
    n.normalize()
    return n


def pick_wire(shape: Part.Shape, index: int = 0) -> Part.Wire:
    wires = shape.Wires
    if not wires:
        if not shape.Edges:
            raise BeltError("selected object has no edges")
        wires = [Part.Wire(es) for es in Part.sortEdges(shape.Edges)]
    if index < 0 or index >= len(wires):
        raise BeltError(f"wire index {index} out of range (path has {len(wires)} wire(s))")
    return wires[index]


# --------------------------------------------------------------------------
# 2D primitives
# --------------------------------------------------------------------------

def _rect(x0, y0, x1, y1):
    xa, xb = sorted((x0, x1))
    ya, yb = sorted((y0, y1))
    return Part.makePlane(xb - xa, yb - ya, V(xa, ya, 0))


def _disk(r, x, y):
    return Part.Face(Part.Wire(Part.makeCircle(r, V(x, y, 0))))


def _merge_faces(shape) -> Part.Shape:
    """Merge the coplanar faces of a 2D boolean result into as few faces as possible.

    A 2D fuse returns adjacent faces that only share edges; wrapping them in a
    shell lets removeSplitter dissolve the shared edges.
    """
    faces = shape.Faces
    if len(faces) <= 1:
        return faces[0] if faces else shape
    # Sew the pieces, then rebuild one face from the free (outline) edges.
    # This keeps holes, which Shell.removeSplitter() silently fills in.
    area = shape.Area

    def area_ok(candidate):
        return len(candidate.Faces) == 1 and abs(candidate.Area - area) <= 1e-6 * max(1.0, area)

    try:
        shell = Part.Shell(faces)
        shell.sewShape()
        outline = shell.getFreeEdges().Edges
        wires = [Part.Wire(group) for group in Part.sortEdges(outline)]
        if wires and all(w.isClosed() for w in wires):
            merged = Part.makeFace(wires, "Part::FaceMakerBullseye")
            if area_ok(merged):
                return merged.Faces[0]
    except (Part.OCCError, ValueError, RuntimeError):
        pass
    # Shell refinement handles faces without holes; the area check rejects it
    # when it has filled a hole in.
    try:
        refined = Part.Shell(faces).removeSplitter()
        if area_ok(refined):
            return refined.Faces[0]
    except (Part.OCCError, ValueError, RuntimeError):
        pass
    # Fallback: leave the pieces separate; build_belt fuses them in 3D.
    return Part.Compound(faces)



def tooth_face(p: BeltProfile, root_offset: float, kappa_left: float,
               kappa_right: float, fillets: bool) -> Part.Shape:
    """One tooth in the local frame (x along the belt, y=0 on the root land).

    The base extends down to the middle of the backing so it always overlaps
    the backing band, even where the root land curves away from the tooth.
    """
    y_ct, y_cf, y_tan = solver.flank_geometry(p.tooth_h, p.tip_r, p.flank_r, p.flank_offset)
    base = -0.5 * p.backing_h
    w = 1.25 * p.flank_r

    lens = _disk(p.flank_r, -p.flank_offset, y_cf).common(_disk(p.flank_r, p.flank_offset, y_cf))
    tooth = lens.common(_rect(-w, base, w, y_tan))
    tip = _disk(p.tip_r, 0.0, y_ct).common(_rect(-w, base, w, p.tooth_h + 1.0))
    tooth = tooth.fuse(tip)

    if fillets and p.root_r > 1e-6:
        for sx, kappa in ((1.0, kappa_right), (-1.0, kappa_left)):
            f = solver.root_fillet(kappa, p.pitch, p.tooth_h, root_offset,
                                   p.tip_r, p.flank_r, p.flank_offset, p.root_r)
            y_bot = max(base * 0.92, f.y_surf - 0.42 * p.backing_h)
            y_top = max(f.y_flank_tan, f.y_surf + 1e-4)
            if f.u_surf <= 1e-6 or y_top - y_bot <= 1e-6:
                continue
            fillet_disk = _disk(p.root_r, sx * f.u_cr, f.y_cr)
            flare = _rect(0.0, y_bot, sx * f.u_surf, y_top).cut(fillet_disk)
            if f.pinched and f.alpha > 1e-4:
                # Keep the fillet from crossing the bisector to the neighbour tooth.
                ca, sa = math.cos(f.alpha), math.sin(f.alpha)
                n = V(sx * ca, sa, 0)
                t = V(-sx * sa, ca, 0)
                o = V(sx * f.u_surf, f.y_surf, 0)
                big = 4.0 * p.pitch
                pts = [o - t * big, o + t * big, o + t * big + n * big, o - t * big + n * big]
                flare = flare.cut(Part.Face(Part.makePolygon(pts + [pts[0]])))
            tooth = tooth.fuse(flare).cut(fillet_disk)
    return _merge_faces(tooth)


# --------------------------------------------------------------------------
# Backing
# --------------------------------------------------------------------------

def _offset_toward(wire, dist, closed, probe, direction, fill=False):
    """Offset ``wire`` by ``dist`` (> 0) toward ``direction`` as seen at ``probe``.

    makeOffset2D's sign convention depends on wire orientation (and the wire it
    returns may be reversed), so try both signs and keep the one that lands on
    the requested side of a known point on ``wire``.
    """
    for signed in (dist, -dist):
        try:
            res = wire.makeOffset2D(signed, 0, fill, not closed)
        except Part.OCCError as exc:
            raise BeltError(f"offset of {dist:.3f} mm failed; a bend is probably too tight") from exc
        if res.isNull():
            continue
        reach = dist * 0.5 if fill else dist
        d_target = res.distToShape(Part.Vertex(probe + direction * reach))[0]
        d_wrong = res.distToShape(Part.Vertex(probe - direction * reach))[0]
        if d_target <= d_wrong + 1e-9:
            return res
    raise BeltError(f"could not offset the path by {dist:.3f} mm")


def backing_band(wire, walker, normal, left_from, left_to):
    """Face covering the band between two signed left-offsets of the pitch line."""
    lo, hi = sorted((left_from, left_to))
    probe, tan = walker.at(0.37 * walker.length)
    left = normal.cross(tan)
    left.normalize()
    if abs(lo) > 1e-9:
        offset = _offset_toward(wire, abs(lo), walker.closed, probe, left * math.copysign(1.0, lo))
        if not offset.Wires:
            raise BeltError("backing offset produced no wire; a bend is probably too tight")
        edge_wire = offset.Wires[0]
        probe = probe + left * lo
    else:
        edge_wire = wire
    band = _offset_toward(edge_wire, hi - lo, walker.closed, probe, left, fill=True)
    if not band.Faces:
        raise BeltError("backing offset produced no face; a bend is probably too tight")
    expected = walker.length * (hi - lo)
    if not 0.5 * expected < band.Area < 1.5 * expected:
        raise BeltError("backing band looks wrong (a bend is probably tighter than the belt allows)")
    return band


# --------------------------------------------------------------------------
# Belt
# --------------------------------------------------------------------------

def build_belt(wire: Part.Wire, normal: App.Vector, profile: str = "GT2", side: str = "Inside",
               width: float = 6.0, symmetric: bool = True, fillets: bool = True) -> BeltResult:
    if profile not in PROFILES:
        raise BeltError(f"unknown profile {profile!r}")
    if side not in SIDES:
        raise BeltError(f"unknown teeth side {side!r}")
    if width <= 0:
        raise BeltError("width must be positive")
    p = PROFILES[profile]
    walker = PathWalker(wire)
    if walker.length <= p.pitch * 0.5:
        raise BeltError("path is shorter than half a tooth pitch")

    # s = +1 puts the teeth on the path's left (normal x tangent).
    if side == "Both":
        tooth_sides = (1.0, -1.0)
        root_offset = 0.5 * p.backing_h
        band_from, band_to = -root_offset, root_offset
    else:
        s = 1.0
        if walker.closed:
            pt, t = walker.at(0.0)
            probe = pt + normal.cross(t) * min(0.05, 0.1 * p.pitch)
            left_is_inside = Part.Face(wire).isInside(probe, 1e-7, True)
            want_inside = side == "Inside"
            s = 1.0 if left_is_inside == want_inside else -1.0
        elif side == "Outside":
            s = -1.0
        tooth_sides = (s,)
        root_offset = p.pld
        band_from, band_to = s * p.pld, s * (p.pld - p.backing_h)

    band = backing_band(wire, walker, normal, band_from, band_to)

    layout = solver.tooth_layout(walker.length, p.pitch, walker.closed)
    sample = 0.35 * p.pitch
    cache = {}
    teeth = []
    for k in range(layout.count):
        dist = layout.start + k * layout.step
        pt, tan = walker.at(dist)
        left = normal.cross(tan)
        left.normalize()
        prev_pt, _ = walker.at(dist - sample)
        next_pt, _ = walker.at(dist + sample)
        for sgn in tooth_sides:
            y_axis = left * sgn
            x_axis = tan * sgn  # keeps the local frame right-handed when mirrored
            origin = pt + y_axis * root_offset
            # Neighbour on local +x is "next" when x follows the path, else "prev".
            right_nb, left_nb = (next_pt, prev_pt) if sgn > 0 else (prev_pt, next_pt)
            if fillets:
                kr = solver.quantize_curvature(solver.side_curvature(
                    (right_nb - pt).dot(x_axis), (right_nb - pt).dot(y_axis)))
                kl = solver.quantize_curvature(solver.side_curvature(
                    (left_nb - pt).dot(x_axis), (left_nb - pt).dot(y_axis)))
            else:
                kr = kl = 0.0
            key = (kl, kr)
            if key not in cache:
                cache[key] = tooth_face(p, root_offset, kl, kr, fillets)
            m = App.Matrix(x_axis.x, y_axis.x, normal.x, origin.x,
                           x_axis.y, y_axis.y, normal.y, origin.y,
                           x_axis.z, y_axis.z, normal.z, origin.z,
                           0, 0, 0, 1)
            tooth = cache[key].copy()
            tooth.Placement = App.Placement(m)
            teeth.append(tooth)

    profile_2d = _merge_faces(band.fuse(teeth) if teeth else band)
    solid = profile_2d.extrude(normal * width)
    if len(solid.Solids) > 1:
        pieces = solid.Solids
        solid = pieces[0].fuse(pieces[1:]).removeSplitter()
    if len(solid.Solids) == 1:
        solid = solid.Solids[0]
    if symmetric:
        # Bake the shift into the geometry: FreeCAD replaces a shape's own
        # Placement with the object's Placement when it is assigned.
        shift = App.Matrix()
        shift.move(normal * (-0.5 * width))
        solid = solid.copy()
        solid.transformShape(shift, True)
    return BeltResult(solid, layout.count, walker.length, layout.pitch_error, walker.closed)
