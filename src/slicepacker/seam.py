"""A torus that may use its seam: the stronger static baseline.

The static model never places or re-forms a slice across the seam of a ring
(ASSUMPTIONS A2, DECISIONS D2): every slice is a rectangle in absolute
coordinates. That rule is about naming, not physics. On a wrapping axis, chips
``15, 0, 1`` are as adjacent as ``0, 1, 2``.

Two consequences, both checked against the OCS mode:

* **Cordon.** A slice that spans a whole ring can drop the failed chip's plane
  and keep the other planes as one slab, contiguous through the seam. That
  costs one plane wherever the chip is, and that axis's ring. The static
  :func:`slicepacker.cordon.cheapest_shrink` only pulls a face inward, so a
  centre failure in a 16-cubed slice costs it eight planes.
* **Placement.** :class:`SeamFabric` lets a slice start anywhere on a wrapping
  axis, so free chips either side of the seam can form one slice.

Nothing here changes :mod:`slicepacker.cordon` or :class:`Fabric`; every
existing output is unchanged. This module is opt-in, and the OCS comparison
reports both baselines. Added for assurance finding A1 (2026-11-09).
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence, Set, Tuple

from .cordon import cheapest_shrink
from .packing import (OBJECTIVES, Fabric, NoPlacement, Request, candidate_shapes,
                      shape_report)
from .torus import Coord, SliceRect

__all__ = ["SeamShrink", "seam_shrinks", "cheapest_shrink_across_seam", "SeamFabric"]


@dataclass(frozen=True)
class SeamShrink:
    """One way back to a single slab after a failure.

    ``kind`` is ``"face"`` (the static cordon's answer), ``"seam"`` (drop the
    failed plane, keep the rest through the seam) or ``"none"`` (nothing
    survives). ``wraps_after`` is per axis: does the survivor still close the
    ring it closed before?
    """

    kind: str
    axis: int
    chips_lost: int
    extent_after: Optional[Coord]
    wraps_after: Optional[Tuple[bool, ...]]


def seam_shrinks(rect: SliceRect, failed: Coord,
                 wraps: Sequence[bool]) -> Tuple[SeamShrink, ...]:
    """Every seam-crossing shrink: one per axis on which ``rect`` closes a ring.

    ``wraps[axis]`` must say whether the slice itself closes a ring on that
    axis (for a static slice, ``rect.wraps_in(pod)``; for a stitched slice,
    :meth:`StitchedSlice.wraps`). An axis with no ring has no seam to cross.
    """
    if not rect.contains(failed):
        raise ValueError(f"{failed} is not inside {rect.canonical()}")
    out = []
    for axis, closed in enumerate(wraps):
        e = rect.extent[axis]
        if not closed or e < 2:
            continue
        plane = rect.chips // e
        extent = rect.extent[:axis] + (e - 1,) + rect.extent[axis + 1:]
        after = tuple(w and i != axis for i, w in enumerate(wraps))
        out.append(SeamShrink("seam", axis, plane, extent, after))
    return tuple(out)


def cheapest_shrink_across_seam(rect: SliceRect, failed: Coord,
                                wraps: Sequence[bool]) -> SeamShrink:
    """The cheaper of the static cordon and a seam-crossing shrink.

    Ties go to the static face shrink: same chips, and the survivor keeps
    absolute coordinates. So the answer differs from
    :func:`~slicepacker.cordon.cheapest_shrink` only where crossing the seam
    is strictly cheaper.
    """
    face = cheapest_shrink(rect, failed)
    if face.rect is None:
        best = SeamShrink("none", 0, rect.chips, None, None)
    else:
        after = tuple(w and e == t for w, e, t
                      in zip(wraps, face.rect.extent, rect.extent))
        best = SeamShrink("face", face.axis, face.chips_lost, tuple(face.rect.extent), after)
    for option in seam_shrinks(rect, failed, wraps):
        if option.chips_lost < best.chips_lost:
            best = option
    return best


def _overlap(a: int, ea: int, b: int, eb: int, t: int, wrap: bool) -> bool:
    if not wrap:
        return a < b + eb and b < a + ea
    return any(a < b + k + eb and b + k < a + ea for k in (-t, 0, t))


class SeamFabric(Fabric):
    """A :class:`Fabric` whose slices may start anywhere on a wrapping axis.

    A slice is still a :class:`SliceRect`: its origin is where it starts, and on
    a wrapping axis ``origin + extent`` may pass the pod's edge, meaning it
    continues from coordinate 0. Rectangles that span a whole axis start at 0,
    so each placement has exactly one name. On an axis that does not wrap,
    behaviour is exactly :class:`Fabric`'s.

    Only what the comparison uses is overridden: occupancy, placement and the
    largest placeable job. :meth:`Fabric.cordon` and topology reports are not
    seam-aware and are not used on this class.
    """

    def _wraps(self) -> Tuple[bool, ...]:
        return tuple(self.pod.wrap)

    def _legal(self, rect: SliceRect) -> bool:
        for o, e, t, w in zip(rect.origin, rect.extent, self.pod.extents, self._wraps()):
            if e > t or o >= t:
                return False
            if o + e > t and not (w and e < t):
                return False
        return True

    def occupied(self) -> Set[Coord]:
        t = self.pod.extents
        out: Set[Coord] = set(self.unhealthy)
        for rect in self.allocations.values():
            out.update(tuple(c % n for c, n in zip(coord, t)) for coord in rect.coords())
        return out

    def _overlaps(self, a: SliceRect, b: SliceRect) -> bool:
        return all(_overlap(ao, ae, bo, be, t, w) for ao, ae, bo, be, t, w in zip(
            a.origin, a.extent, b.origin, b.extent, self.pod.extents, self._wraps()))

    def _contains(self, rect: SliceRect, coord: Coord) -> bool:
        return all((c - o) % t < e for c, o, e, t
                   in zip(coord, rect.origin, rect.extent, self.pod.extents))

    def is_free(self, rect: SliceRect) -> bool:
        if not self._legal(rect):
            return False
        if any(self._overlaps(rect, other) for other in self.allocations.values()):
            return False
        return not any(self._contains(rect, c) for c in self.unhealthy)

    def _origin_ranges(self, shape: Coord):
        return [range(t) if (w and e < t) else range(t - e + 1)
                for t, e, w in zip(self.pod.extents, shape, self._wraps())]

    def positions(self, shape: Coord) -> Iterable[SliceRect]:
        ranges = self._origin_ranges(shape)
        if any(len(r) == 0 for r in ranges):
            return ()
        return (SliceRect(origin, shape) for origin in itertools.product(*ranges))

    # -- the fast path: free space as bitmasks -----------------------------
    #
    # Scanning every origin of every shape with a modular overlap test took
    # over ten minutes for the comparison's quick mode. Instead each line along
    # axis 0 is an int whose bits are its free chips; a run of ``a`` free chips
    # starting at x is ``m & rot(m, 1) & ... & rot(m, a-1)``, and the other two
    # axes AND lines together. Shapes that do not fit stop the search early,
    # because a shape containing one that does not fit does not fit either.

    def _dims(self):
        t, w = tuple(self.pod.extents), tuple(self.pod.wrap)
        if len(t) > 3:
            raise NotImplementedError("SeamFabric handles up to three axes")
        pad = 3 - len(t)
        return t + (1,) * pad, w + (False,) * pad

    def _free_grid(self):
        (X, Y, Z), _ = self._dims()
        full = (1 << X) - 1
        grid = [[full] * Z for _ in range(Y)]
        for c in self.occupied():
            x, y, z = tuple(c) + (0,) * (3 - len(c))
            grid[y][z] &= ~(1 << x)
        return grid

    @staticmethod
    def _rot(m: int, k: int, n: int, wrap: bool) -> int:
        if not k:
            return m
        if wrap:
            return ((m >> k) | (m << (n - k))) & ((1 << n) - 1)
        return m >> k

    def _fit_grid(self, shape: Coord, free=None):
        """Per (y, z), the bitmask of x origins at which ``shape`` lands on
        free chips, with each placement given one name: a slice spanning an
        axis starts at 0 on it, and on an axis that does not wrap it ends
        inside the pod."""
        (X, Y, Z), (wx, wy, wz) = self._dims()
        a, b, c = tuple(shape) + (1,) * (3 - len(shape))
        if a > X or b > Y or c > Z:
            return None
        free = free if free is not None else self._free_grid()
        A = [[0] * Z for _ in range(Y)]
        for y in range(Y):
            for z in range(Z):
                m = free[y][z]
                run = m
                for k in range(1, a):
                    run &= self._rot(m, k, X, wx)
                A[y][z] = run & 1 if a == X else run
        out = [[0] * Z for _ in range(Y)]
        for y in range(Y):
            if (b == Y and y) or (not wy and y + b > Y):
                continue
            for z in range(Z):
                if (c == Z and z) or (not wz and z + c > Z):
                    continue
                m = -1
                for j in range(b):
                    for k in range(c):
                        m &= A[(y + j) % Y][(z + k) % Z]
                        if not m:
                            break
                    if not m:
                        break
                out[y][z] = m if m > 0 else 0
        return out

    def _first_origin(self, shape: Coord) -> Optional[Coord]:
        grid = self._fit_grid(shape)
        if grid is None:
            return None
        best = None
        for y, row in enumerate(grid):
            for z, m in enumerate(row):
                if m:
                    x = (m & -m).bit_length() - 1
                    if best is None or (x, y, z) < best:
                        best = (x, y, z)
        return None if best is None else best[:self.pod.ndim]

    def place(self, request: Request, *, objective: str = "diameter") -> SliceRect:
        """:meth:`Fabric.place`, with origins anywhere on a wrapping axis.

        Same shape order, same first-fit rule (the lowest origin in the order
        :meth:`positions` lists them), found from the bitmasks."""
        if request.shape is not None:
            shapes: Sequence[Coord] = (request.shape,)
        else:
            reports = [shape_report(s, self.pod)
                       for s in candidate_shapes(request.chips, self.pod)]
            reports = [r for r in reports if r["torus_dims"] >= request.min_torus_dims]
            shapes = [r["shape"] for r in sorted(reports, key=OBJECTIVES[objective])]
        if not shapes:
            raise NoPlacement(f"{request.job_id}: no shape of {request.chips} chips fits")
        for shape in shapes:
            if request.shape is not None:
                topo = SliceRect((0,) * self.pod.ndim, shape).topology(self.pod)
                if sum(topo.wrap) < request.min_torus_dims:
                    continue
            origin = self._first_origin(shape)
            if origin is not None:
                rect = SliceRect(tuple(origin), tuple(shape))
                self.allocations[request.job_id] = rect
                return rect
        raise NoPlacement(f"{request.job_id}: {request.chips} chips do not fit, "
                          "even across the seam")

    def largest_placeable(self, *, min_torus_dims: int = 0) -> int:
        if min_torus_dims:
            raise NotImplementedError("SeamFabric reports no topology")
        (X, Y, Z), (wx, wy, wz) = self._dims()
        free = self._free_grid()
        best = 0
        A = [row[:] for row in free]
        for a in range(1, X + 1):
            if a > 1:
                A = [[A[y][z] & self._rot(free[y][z], a - 1, X, wx) for z in range(Z)]
                     for y in range(Y)]
            if not any(any(row) for row in A):
                break
            B = [row[:] for row in A]
            for b in range(1, Y + 1):
                if b > 1:
                    B = [[(B[y][z] & A[(y + b - 1) % Y][z])
                          if (wy or y + b <= Y) else 0 for z in range(Z)]
                         for y in range(Y)]
                if not any(any(row) for row in B):
                    break
                C = [row[:] for row in B]
                for c in range(1, Z + 1):
                    if c > 1:
                        C = [[(C[y][z] & B[y][(z + c - 1) % Z])
                              if (wz or z + c <= Z) else 0 for z in range(Z)]
                             for y in range(Y)]
                    if not any(any(row) for row in C):
                        break
                    best = max(best, a * b * c)
        return best
