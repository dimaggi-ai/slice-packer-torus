"""A torus, the rectangles you can cut out of it, and what the cut costs.

Accelerator fabrics of the pod-and-slice kind are k-ary n-cubes: a grid with
wraparound links closing each dimension into a ring. A tenant does not get the
pod, they get a rectangular sub-grid of it, and the arithmetic of that
rectangle decides more about the job's collective performance than the chip
count does.

The fact this module exists to make computable:

    A slice inherits the wraparound in a dimension only if it spans that
    dimension completely.

A 4x4x4 slice of an 8x8x8 pod is a *mesh* in all three dimensions --- no
wraparound anywhere --- while a 4x8x8 slice of the same pod, with the same
number of chips as an 8x4x8 one but a different shape, wraps in two dimensions
and meshes in one. Same chip count, different diameter, different bisection.
Anyone sizing a job in chips alone has thrown away the number that matters.

The closed forms here are the published ones for k-ary n-cubes (Dally and
Towles, *Principles and Practices of Interconnection Networks*, is the standard
reference):

===================== ================================ ==========================
quantity              torus (wraps)                    mesh (does not)
===================== ================================ ==========================
diameter              ``n * floor(k / 2)``             ``n * (k - 1)``
bisection (links cut) ``2 * k**(n - 1)``               ``k**(n - 1)``
===================== ================================ ==========================

They are not asserted. :mod:`slicepacker.torus` builds the actual graph and the
validation registry checks the closed forms against brute-force enumeration ---
every shortest path for the diameter, and every balanced bipartition for the
bisection. If the formulas and the graph disagree, the registry goes red.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

Coord = Tuple[int, ...]


@dataclass(frozen=True)
class Topology:
    """A pod: extents per dimension, and which dimensions wrap."""

    extents: Tuple[int, ...]
    wrap: Tuple[bool, ...]

    def __post_init__(self) -> None:
        if not self.extents:
            raise ValueError("a topology needs at least one dimension")
        if len(self.extents) != len(self.wrap):
            raise ValueError("extents and wrap must have the same length")
        for e in self.extents:
            if e < 1:
                raise ValueError("every extent must be at least 1")
        for e, w in zip(self.extents, self.wrap):
            if w and e < 3:
                raise ValueError(
                    f"a dimension of extent {e} cannot wrap into a useful ring: at "
                    "extent 1 the wraparound is a self-loop and at extent 2 it "
                    "duplicates the link that is already there. Declare it as mesh"
                )

    @classmethod
    def cube(cls, k: int, n: int, *, wrap: bool = True) -> "Topology":
        """The k-ary n-cube of the textbooks."""
        return cls((k,) * n, (wrap,) * n)

    @property
    def ndim(self) -> int:
        return len(self.extents)

    @property
    def chips(self) -> int:
        return math.prod(self.extents)

    def coords(self) -> Iterator[Coord]:
        return itertools.product(*(range(e) for e in self.extents))

    def neighbours(self, coord: Coord) -> List[Coord]:
        """Every chip one hop away. Wraparound included where a dimension wraps."""
        out: List[Coord] = []
        for axis, extent in enumerate(self.extents):
            for step in (-1, 1):
                value = coord[axis] + step
                if 0 <= value < extent:
                    pass
                elif self.wrap[axis]:
                    value %= extent
                else:
                    continue
                if value == coord[axis]:
                    continue  # extent 1: stepping lands where you started
                candidate = coord[:axis] + (value,) + coord[axis + 1:]
                if candidate not in out:
                    out.append(candidate)
        return out

    # -- closed forms ---------------------------------------------------------

    def diameter(self) -> int:
        """Longest shortest path, from the closed form.

        Checked against brute-force breadth-first search by the registry.
        """
        total = 0
        for extent, wraps in zip(self.extents, self.wrap):
            total += extent // 2 if wraps else extent - 1
        return total

    def bisection_links(self) -> int:
        """Bidirectional links crossing the cheapest dimensional cut.

        Cutting perpendicular to one axis severs the plane of links crossing it
        --- twice over if that axis wraps, because a ring has two ways round.
        The cheapest cut is perpendicular to the axis whose *other* dimensions
        are smallest.

        This counts the cheapest **dimensional** cut. That it is also the
        minimum over all balanced bipartitions is a separate claim, and the
        registry checks it by enumeration rather than assuming it.
        """
        best = None
        for axis, extent in enumerate(self.extents):
            if extent < 2:
                continue
            plane = math.prod(e for i, e in enumerate(self.extents) if i != axis)
            cut = plane * (2 if self.wrap[axis] else 1)
            best = cut if best is None else min(best, cut)
        return best if best is not None else 0

    def links(self) -> int:
        """Total bidirectional links."""
        total = 0
        for axis, extent in enumerate(self.extents):
            if extent < 2:
                continue
            plane = math.prod(e for i, e in enumerate(self.extents) if i != axis)
            total += plane * (extent if self.wrap[axis] else extent - 1)
        return total

    # -- brute force, for the registry to check the closed forms against ------

    def graph(self) -> Dict[Coord, List[Coord]]:
        return {c: self.neighbours(c) for c in self.coords()}

    def measured_diameter(self) -> int:
        """Breadth-first search from every chip. Exact, and slow on purpose."""
        graph = self.graph()
        worst = 0
        for source in graph:
            seen = {source: 0}
            frontier = [source]
            while frontier:
                nxt = []
                for node in frontier:
                    for peer in graph[node]:
                        if peer not in seen:
                            seen[peer] = seen[node] + 1
                            nxt.append(peer)
                frontier = nxt
            if len(seen) != self.chips:
                raise ValueError("topology is disconnected")
            worst = max(worst, max(seen.values()))
        return worst

    def measured_bisection(self) -> int:
        """Minimum cut over every balanced bipartition. Exponential; small only."""
        nodes = list(self.coords())
        if len(nodes) > 20:
            raise ValueError(
                f"{len(nodes)} chips is too many for exact bisection: the search is "
                "over every balanced bipartition. Keep this to toy topologies"
            )
        if len(nodes) % 2:
            raise ValueError("an odd chip count has no balanced bipartition")
        index = {c: i for i, c in enumerate(nodes)}
        edges = set()
        for coord in nodes:
            for peer in self.neighbours(coord):
                edges.add(tuple(sorted((index[coord], index[peer]))))
        half = len(nodes) // 2
        best = None
        first = 0  # pin one node to avoid counting each partition twice
        for rest in itertools.combinations(range(1, len(nodes)), half - 1):
            side = {first, *rest}
            cut = sum(1 for a, b in edges if (a in side) != (b in side))
            best = cut if best is None else min(best, cut)
        return best or 0


@dataclass(frozen=True)
class SliceRect:
    """A rectangular sub-grid: an origin and an extent per dimension."""

    origin: Coord
    extent: Coord

    def __post_init__(self) -> None:
        if len(self.origin) != len(self.extent):
            raise ValueError("origin and extent must have the same length")
        for o, e in zip(self.origin, self.extent):
            if o < 0:
                raise ValueError("origin coordinates must be non-negative")
            if e < 1:
                raise ValueError("every extent must be at least 1")

    @property
    def ndim(self) -> int:
        return len(self.extent)

    @property
    def chips(self) -> int:
        return math.prod(self.extent)

    def coords(self) -> Iterator[Coord]:
        return itertools.product(
            *(range(o, o + e) for o, e in zip(self.origin, self.extent))
        )

    def contains(self, coord: Coord) -> bool:
        return all(o <= c < o + e for c, o, e in zip(coord, self.origin, self.extent))

    def overlaps(self, other: "SliceRect") -> bool:
        return all(
            a_o < b_o + b_e and b_o < a_o + a_e
            for a_o, a_e, b_o, b_e in zip(
                self.origin, self.extent, other.origin, other.extent
            )
        )

    def fits_in(self, topology: Topology) -> bool:
        return all(
            o + e <= t for o, e, t in zip(self.origin, self.extent, topology.extents)
        )

    def canonical(self) -> str:
        return ",".join(f"{o}+{e}" for o, e in zip(self.origin, self.extent))

    # -- the part that matters -----------------------------------------------

    def wraps_in(self, topology: Topology) -> Tuple[bool, ...]:
        """Per dimension: does this slice inherit the pod's wraparound?

        Only by spanning the dimension completely. A slice that leaves even one
        chip of a ring outside itself has a line, not a ring, and every
        collective that assumed otherwise is now running on a mesh.
        """
        return tuple(
            pod_wraps and extent == pod_extent
            for pod_wraps, extent, pod_extent in zip(
                topology.wrap, self.extent, topology.extents
            )
        )

    def topology(self, pod: Topology) -> Topology:
        """The topology this slice actually presents to a job running on it."""
        if not self.fits_in(pod):
            raise ValueError(f"slice {self.canonical()} does not fit in the pod")
        return Topology(tuple(self.extent), self.wraps_in(pod))

    def torus_dims(self, pod: Topology) -> int:
        return sum(self.wraps_in(pod))
