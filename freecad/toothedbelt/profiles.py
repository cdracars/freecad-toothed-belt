"""Timing belt tooth profiles (all values in mm).

Ported from TurtleCrawler/Fusion-ToothedBeltGenerator (MIT). The tooth-shape
radii (tip_r, flank_r, flank_offset, root_r) are the original add-in's values
and have NOT yet been checked against manufacturer drawings or measured belts.
Treat them as a close approximation until they are.

Fields:
    pitch         tooth-to-tooth spacing along the pitch line
    tooth_h       tooth height above the root land
    backing_h     thickness of the backing (root land to back face)
    pld           pitch line differential: pitch line to root land distance
    tip_r         tooth tip radius
    flank_r       flank arc radius
    flank_offset  horizontal offset of each flank arc centre from the tooth axis
    root_r        root fillet radius (tooth flank to root land)
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class BeltProfile:
    name: str
    pitch: float
    tooth_h: float
    backing_h: float
    pld: float
    tip_r: float
    flank_r: float
    flank_offset: float
    root_r: float

    @property
    def total_h(self) -> float:
        return self.tooth_h + self.backing_h

    @property
    def backside_offset(self) -> float:
        """Distance from the pitch line to the back face of the belt."""
        return self.backing_h - self.pld


PROFILES = {
    p.name: p
    for p in (
        BeltProfile("GT2", pitch=2.00, tooth_h=0.75, backing_h=0.63, pld=0.254,
                    tip_r=0.555, flank_r=1.00, flank_offset=0.40, root_r=0.150),
        BeltProfile("GT1.5", pitch=1.50, tooth_h=0.56, backing_h=0.44, pld=0.230,
                    tip_r=0.415, flank_r=0.75, flank_offset=0.30, root_r=0.115),
        BeltProfile("HTD 5M", pitch=5.00, tooth_h=2.06, backing_h=1.74, pld=0.5715,
                    tip_r=1.49, flank_r=2.50, flank_offset=0.83, root_r=0.43),
        BeltProfile("HTD 8M", pitch=8.00, tooth_h=3.38, backing_h=2.62, pld=0.686,
                    tip_r=2.46, flank_r=4.10, flank_offset=1.36, root_r=0.68),
    )
}

DEFAULT_PROFILE = "GT2"
