"""Choosing a shape, placing it, and counting what is left over.

A request arrives for a number of chips. Turning that into a rectangle is a
choice, and it is the choice this module is mostly about, because:

* the shapes that fit a given chip count are few and very different from each
  other --- 4,096 chips in a 64-cubed pod has 28 legal shapes, from a
  ``1 x 64 x 64`` sheet to a ``16 x 16 x 16`` cube;
* the shape with the most wraparound dimensions is frequently *not* the shape
  with the best diameter or the best bisection, so a packer that maximises
  torus-ness gives the job a worse network than one that maximises compactness;
* and the shape you pick determines what rectangles remain placeable for
  everyone after you, which is where fragmentation comes from.

Free chips are not free capacity. A pod can be two-thirds empty and unable to
admit a single job, because the empty chips do not form a rectangle. That
number --- placeable capacity, not free capacity --- is what
:meth:`Fabric.fragmentation` reports.
"""

from __future__ import annotations

import functools
import itertools
import math
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .torus import Coord, SliceRect, Topology


class NoPlacement(Exception):
    """No legal rectangle of the requested size fits anywhere free."""


@dataclass(frozen=True)
class Request:
    """A tenant wants this many chips, under these constraints."""

    job_id: str
    chips: int
    #: If given, the only shape that will be accepted.
    shape: Optional[Coord] = None
    #: Minimum wraparound dimensions the job needs. Set this only when the job
    #: genuinely relies on a ring --- see the module docstring for why raising
    #: it is not the free improvement it looks like.
    min_torus_dims: int = 0
    tenant: str = ""
    priority: int = 0

    def __post_init__(self) -> None:
        if self.chips < 1:
            raise ValueError("a request needs at least one chip")
        if self.shape is not None and math.prod(self.shape) != self.chips:
            raise ValueError(
                f"shape {self.shape} holds {math.prod(self.shape)} chips, "
                f"not the {self.chips} requested"
            )
        if self.min_torus_dims < 0:
            raise ValueError("min_torus_dims cannot be negative")


def candidate_shapes(chips: int, pod: Topology) -> Tuple[Coord, ...]:
    """Every rectangular shape of ``chips`` chips that fits inside ``pod``.

    Ordered deterministically --- by compactness, then lexically --- so a packer
    built on this is reproducible. Compactness is the sum of extents, which is
    minimised by the most cube-like shape and is a good proxy for diameter
    without computing one.
    """
    if chips < 1:
        return ()
    results: List[Coord] = []

    def walk(axis: int, remaining: int, prefix: Tuple[int, ...]) -> None:
        if axis == pod.ndim - 1:
            if remaining <= pod.extents[axis]:
                results.append(prefix + (remaining,))
            return
        for extent in range(1, pod.extents[axis] + 1):
            if remaining % extent == 0:
                walk(axis + 1, remaining // extent, prefix + (extent,))

    walk(0, chips, ())
    return tuple(sorted(results, key=lambda s: (sum(s), s)))


def shape_report(shape: Coord, pod: Topology) -> Dict[str, object]:
    """Diameter, bisection and wraparound for a shape, without placing it."""
    topo = SliceRect((0,) * pod.ndim, shape).topology(pod)
    return {
        "shape": shape,
        "chips": math.prod(shape),
        "torus_dims": sum(topo.wrap),
        "diameter": topo.diameter(),
        "bisection": topo.bisection_links(),
    }


#: Ready-made objectives for :func:`best_shape`. Each returns a sort key where
#: smaller is better, so they can be compared on equal terms.
OBJECTIVES: Dict[str, Callable[[Dict[str, object]], Tuple]] = {
    # Compactness. Usually the right default: it minimises diameter, and on a
    # torus pod it tends to maximise bisection too.
    "diameter": lambda r: (r["diameter"], -r["bisection"], r["shape"]),
    "bisection": lambda r: (-r["bisection"], r["diameter"], r["shape"]),
    # Kept because people ask for it, and because the registry demonstrates it
    # is frequently the wrong thing to ask for.
    "torus_dims": lambda r: (-r["torus_dims"], r["diameter"], r["shape"]),
}


def best_shape(
    chips: int,
    pod: Topology,
    *,
    objective: str = "diameter",
    min_torus_dims: int = 0,
) -> Optional[Coord]:
    """The best shape for this many chips under one objective."""
    if objective not in OBJECTIVES:
        raise ValueError(
            f"unknown objective {objective!r}; have {', '.join(sorted(OBJECTIVES))}"
        )
    reports = [shape_report(s, pod) for s in candidate_shapes(chips, pod)]
    reports = [r for r in reports if r["torus_dims"] >= min_torus_dims]
    if not reports:
        return None
    return min(reports, key=OBJECTIVES[objective])["shape"]


@functools.lru_cache(maxsize=32)
def _shapes_by_volume(extents: Coord) -> Tuple[Tuple[Coord, int], ...]:
    """Every rectangle shape fitting these bounds, largest volume first.

    Paired with its volume, and cached per pod: the list depends only on the
    extents, and rebuilding it --- or recomputing the volumes --- for every
    capacity question dominated the cost of asking one.
    """
    shapes = [(s, math.prod(s))
              for s in itertools.product(*(range(1, e + 1) for e in extents))]
    shapes.sort(key=lambda pair: (-pair[1], pair[0]))
    return tuple(shapes)


@dataclass
class Fabric:
    """A pod, what is allocated on it, and what is out of service."""

    pod: Topology
    allocations: Dict[str, SliceRect] = field(default_factory=dict)
    unhealthy: Set[Coord] = field(default_factory=set)

    def __post_init__(self) -> None:
        for coord in self.unhealthy:
            if len(coord) != self.pod.ndim:
                raise ValueError(f"{coord} is not a coordinate in this pod")

    # -- occupancy -----------------------------------------------------------

    def occupied(self) -> Set[Coord]:
        out: Set[Coord] = set(self.unhealthy)
        for rect in self.allocations.values():
            out.update(rect.coords())
        return out

    def free_chips(self) -> int:
        return self.pod.chips - len(self.occupied())

    def allocated_chips(self) -> int:
        return sum(r.chips for r in self.allocations.values())

    def is_free(self, rect: SliceRect) -> bool:
        """Does this rectangle land entirely on free, healthy ground?

        Tested by rectangle overlap rather than by walking the rectangle's
        chips: the coordinate walk is O(volume) and gets called once per
        candidate position, which made a capacity report on a 16-cubed pod take
        minutes. Overlap is O(allocations) and gives the identical answer.
        """
        if not rect.fits_in(self.pod):
            return False
        for other in self.allocations.values():
            if rect.overlaps(other):
                return False
        for coord in self.unhealthy:
            if rect.contains(coord):
                return False
        return True

    # -- placement -----------------------------------------------------------

    def positions(self, shape: Coord) -> Iterable[SliceRect]:
        """Every origin at which ``shape`` fits inside the pod's bounds.

        Origins only, no wraparound placement: a slice that straddles the seam
        of a ring is still a rectangle in the ring's own coordinates, but every
        scheduler and every operator names chips by absolute position, and a
        slice reported as ``60..3`` costs more in confusion than it recovers in
        packing. ASSUMPTIONS A2.
        """
        ranges = [range(0, t - e + 1) for t, e in zip(self.pod.extents, shape)]
        if any(len(r) == 0 for r in ranges):
            return ()
        return (SliceRect(origin, shape) for origin in itertools.product(*ranges))

    def place(self, request: Request, *, objective: str = "diameter") -> SliceRect:
        """Find and take a slice for this request, or raise :class:`NoPlacement`."""
        shapes: Sequence[Coord]
        if request.shape is not None:
            shapes = (request.shape,)
        else:
            reports = [shape_report(s, self.pod)
                       for s in candidate_shapes(request.chips, self.pod)]
            reports = [r for r in reports
                       if r["torus_dims"] >= request.min_torus_dims]
            shapes = [r["shape"] for r in sorted(reports, key=OBJECTIVES[objective])]

        if not shapes:
            raise NoPlacement(
                f"{request.job_id}: no shape of {request.chips} chips fits a "
                f"{'x'.join(map(str, self.pod.extents))} pod with "
                f"{request.min_torus_dims} wraparound dimension(s)"
            )
        for shape in shapes:
            if request.shape is not None:
                topo = SliceRect((0,) * self.pod.ndim, shape).topology(self.pod)
                if sum(topo.wrap) < request.min_torus_dims:
                    continue
            for rect in self.positions(shape):
                if self.is_free(rect):
                    self.allocations[request.job_id] = rect
                    return rect
        raise NoPlacement(
            f"{request.job_id}: {request.chips} chips do not fit; "
            f"{self.free_chips()} chips are free but no legal rectangle among "
            f"{len(shapes)} candidate shape(s) lands on free ground"
        )

    def release(self, job_id: str) -> SliceRect:
        if job_id not in self.allocations:
            raise KeyError(job_id)
        return self.allocations.pop(job_id)

    # -- what is left --------------------------------------------------------

    def can_place(self, chips: int, *, min_torus_dims: int = 0) -> bool:
        probe = Request(job_id="__probe__", chips=chips, min_torus_dims=min_torus_dims)
        for shape in candidate_shapes(chips, self.pod):
            topo = SliceRect((0,) * self.pod.ndim, shape).topology(self.pod)
            if sum(topo.wrap) < min_torus_dims:
                continue
            if any(self.is_free(rect) for rect in self.positions(shape)):
                return True
        return False

    def largest_placeable(self, *, min_torus_dims: int = 0) -> int:
        """The biggest chip count that could still be placed right now.

        This is the number a capacity report should print instead of the
        free-chip count.

        Every rectangle that fits the pod's bounds is tried largest-first, so
        the first one that lands on free ground is the answer. Two earlier
        versions were unusable: one counted downward a chip at a time and asked
        :meth:`can_place` each time, repeating the same position scan thousands
        of times; the next built a :class:`SliceRect` per candidate position,
        which cost more than the test it was feeding. The loop below works on
        raw tuples for that reason, and is the one place in this package where
        speed was allowed to shape the code.
        """
        free = self.free_chips()
        extents = self.pod.extents
        boxes = [(r.origin, tuple(o + e for o, e in zip(r.origin, r.extent)))
                 for r in self.allocations.values()]
        sick = tuple(self.unhealthy)
        ndim = self.pod.ndim

        for shape, volume in _shapes_by_volume(extents):
            if volume > free:
                continue
            if min_torus_dims:
                topo = SliceRect((0,) * ndim, shape).topology(self.pod)
                if sum(topo.wrap) < min_torus_dims:
                    continue
            for origin in itertools.product(
                    *(range(t - e + 1) for t, e in zip(extents, shape))):
                end = tuple(o + e for o, e in zip(origin, shape))
                if any(all(origin[i] < hi[i] and lo[i] < end[i] for i in range(ndim))
                       for lo, hi in boxes):
                    continue
                if any(all(origin[i] <= c[i] < end[i] for i in range(ndim))
                       for c in sick):
                    continue
                return volume
        return 0

    def fragmentation(self, *, min_torus_dims: int = 0) -> float:
        """Fraction of free chips that cannot be part of any single placement.

        Zero when the whole free space is one usable rectangle. One when the pod
        has free chips and can admit nothing at all.
        """
        free = self.free_chips()
        if free == 0:
            return 0.0
        return 1.0 - self.largest_placeable(min_torus_dims=min_torus_dims) / free

    def unservable(self, demand: Sequence[Request]) -> Tuple[Request, ...]:
        """Which pending requests cannot be placed on the fabric as it stands.

        Each is tested against the current state independently, not as a
        sequence: this answers "which of these could I admit right now", not
        "can I admit all of them", which is a different and harder question.
        """
        out = []
        for request in demand:
            if request.shape is not None:
                fits = any(self.is_free(r) for r in self.positions(request.shape))
            else:
                fits = self.can_place(request.chips,
                                      min_torus_dims=request.min_torus_dims)
            if not fits:
                out.append(request)
        return tuple(out)

    # -- derivations (never mutate the receiver) -----------------------------

    def copy(self) -> "Fabric":
        return Fabric(self.pod, dict(self.allocations), set(self.unhealthy))

    def without(self, *job_ids: str) -> "Fabric":
        """A copy with these jobs gone. Unknown ids are an error, not a no-op."""
        out = self.copy()
        for job_id in job_ids:
            out.release(job_id)
        return out

    def cordon(self, *coords: Coord) -> "Fabric":
        """A copy with these chips out of service.

        Allocations are left exactly as they are. A cordoned chip inside a live
        slice makes that slice non-rectangular, which this class has no way to
        represent and deliberately does not try to: see
        :mod:`slicepacker.cordon`, which is where the shrink is decided.
        """
        out = self.copy()
        for coord in coords:
            if len(coord) != self.pod.ndim:
                raise ValueError(f"{coord} is not a coordinate in this pod")
            if any(c < 0 or c >= t for c, t in zip(coord, self.pod.extents)):
                raise ValueError(f"{coord} is outside the pod")
            out.unhealthy.add(coord)
        return out

    def free_positions(self, shape: Coord) -> Iterable[SliceRect]:
        """Every position of ``shape`` that lands entirely on free ground."""
        return (rect for rect in self.positions(shape) if self.is_free(rect))

    def report(self) -> str:
        free = self.free_chips()
        placeable = self.largest_placeable()
        lines = [
            f"pod {'x'.join(map(str, self.pod.extents))}  "
            f"wrap {''.join('T' if w else '-' for w in self.pod.wrap)}  "
            f"{self.pod.chips:,} chips",
            f"  allocated  {self.allocated_chips():,} in {len(self.allocations)} slice(s)",
            f"  unhealthy  {len(self.unhealthy):,}",
            f"  free       {free:,}",
            f"  placeable  {placeable:,}   <- the number a capacity report should print",
        ]
        if free:
            lines.append(f"  fragmented {self.fragmentation() * 100:.0f}% of free chips "
                         f"cannot join any single placement")
        for job_id, rect in sorted(self.allocations.items()):
            topo = rect.topology(self.pod)
            lines.append(
                f"    {job_id:<16} {rect.canonical():<20} {rect.chips:>6,} chips  "
                f"wrap {sum(topo.wrap)}d  diam {topo.diameter()}  "
                f"bisec {topo.bisection_links()}"
            )
        return "\n".join(lines)
