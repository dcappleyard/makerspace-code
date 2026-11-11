"""The sculpture's pixel layout as numpy arrays: what shows receive as `meta`.

All arrays are length N (200) and aligned to the DDP pixel index, so a show
returns rows in the same order.
"""
from pathlib import Path

import numpy as np

import pixel_map

STRANDS = ("3to5", "5to3")


class Layout:
    def __init__(self, rows):
        self.n = len(rows)
        col = lambda k, dt=None: np.array([r[k] for r in rows], dtype=dt)  # noqa: E731

        self.index = col("index", int)
        self.xyz = np.column_stack([col("x", float), col("y", float), col("z", float)])
        self.x, self.y, self.z = self.xyz.T
        self.output = col("output", int)          # 1 or 2
        self.light = col("light", int)            # 1..100 along its string
        self.strand = col("strand")               # "3to5" / "5to3"
        self.strand_id = np.array([STRANDS.index(s) for s in self.strand])
        self.base_pair = col("base_pair", int)    # 0 bottom .. 9 top
        self.part = col("part")                   # "stem" / "ring" / "rod"
        self.slot = col("slot", int)

        self.stem = self.part == "stem"
        self.ring = self.part == "ring"
        self.rod = self.part == "rod"

        # Derived geometry, handy for effects
        self.r = np.hypot(self.x, self.y)                       # distance from the rod axis
        self.theta = np.arctan2(self.y, self.x)                 # angle about the rod, radians
        zmin, zmax = self.z.min(), self.z.max()
        self.h = (self.z - zmin) / (zmax - zmin)                # 0 bottom .. 1 top
        self.n_base_pairs = int(self.base_pair.max()) + 1
        self.bp_frac = self.base_pair / max(1, self.n_base_pairs - 1)   # 0 .. 1 by base pair
        self.strand_pos = (self.light - 1) / (self.light.max() - 1)     # 0 plug end .. 1 top end

        # Angle of each pixel's lollipop (the helix phase). Ring lights are evenly
        # spaced, so their mean is the ring center. Rod lights use their own angle.
        self.lollipop_theta = self.theta.copy()
        for o in (1, 2):
            for bp in range(self.n_base_pairs):
                sel = (self.output == o) & (self.base_pair == bp)
                ring = sel & self.ring
                if ring.any():
                    cx, cy = self.x[ring].mean(), self.y[ring].mean()
                    self.lollipop_theta[sel & ~self.rod] = np.arctan2(cy, cx)

        # Angle around the ring, 0..1, clockwise from above starting after the
        # stem joint (matches slot order); NaN off the ring.
        self.ring_pos = np.where(self.ring, (self.slot + 0.5) / 5, np.nan)

    @classmethod
    def load(cls, path=None):
        return cls(pixel_map.load(path or Path(pixel_map.HERE) / "pixels.csv"))
