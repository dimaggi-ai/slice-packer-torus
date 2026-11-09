"""Optical-circuit-switched cubes: the pod is a set of cubes, not one torus.

Everything else in this package assumes one static torus: a slice is a
rectangle cut out of fixed wiring, inherits a ring only by spanning the whole
pod axis, and gets back to a rectangle after a failure only by pulling a face in
past the dead chip. This module models the other way to build a pod --- the one
described publicly for TPU v4 (Jouppi et al., ISCA 2023) and offered as GKE
"dynamic slicing" --- and exists so the two can be compared on matched inputs.

The model, stated so it can be disagreed with:

* **A pod is a set of cubes.** Each cube is a fixed electrical mesh of
  ``geometry`` chips (default ``4x4x4``; 64 chips per cube, as in the TPU v4
  paper). Cubes have no fixed position relative to each other.
* **Every cube face reaches the optical switches.** On each axis a cube face
  carries one link per face position (16 on a ``4x4x4`` face). Face position
  ``p`` on axis ``d`` goes to OCS ``(d, p)``, so there are
  ``sum(face links per axis)`` switches (48 for ``4x4x4``) and every cube uses
  exactly two ports --- its ``+`` and ``-`` face --- on each switch. An OCS of
  ``ocs_ports`` usable ports therefore serves at most ``ocs_ports // 2`` cubes.
  That group of cubes is a **domain**, and stitching never crosses one.
* **Super-slicing** stitches whole cubes into a rectangle of cubes. Any free,
  healthy cubes in one domain will do: adjacency does not exist, so a slice
  needs a *count* of free cubes, not a free *region*.
* **Sub-slicing** carves a job smaller than a cube out of one cube, from a
  short list of shapes (GKE documents ``2x2x1, 2x2x2, 2x2x4, 2x4x4``). Inside a
  cube the problem is the static one, so it is solved with the existing
  :class:`~slicepacker.packing.Fabric`.
* **The ring is a circuit, never an assumption.** A stitched slice has a
  wraparound in an axis if and only if the OCS was told to connect the last
  cube's ``+`` face back to the first cube's ``-`` face on every line along that
  axis. :meth:`StitchedSlice.wraps` derives it from the circuit list, and
  :func:`stitched_graph` builds the chip graph from the same list so the
  registry can check the two by breadth-first search.

What it does **not** model --- each a place the answers could move: optical
insertion loss and the latency of a switched hop (a circuit counts as one hop,
like an electrical link); the time an OCS takes to reconfigure (the vendor's
5x/4.5x start and recovery claims are not inputs anywhere); OCS failure; twisted
tori; host and rack boundaries; and any scheduling policy beyond first-fit at
cube granularity.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Sequence, Set, Tuple

from .cordon import cheapest_shrink
from .packing import Fabric, NoPlacement, Request, candidate_shapes
from .torus import Coord, SliceRect, Topology

#: One bundle of fibres: on ``axis``, the ``+`` face of cube ``src`` is
#: connected to the ``-`` face of cube ``dst``, on every face position (one OCS
#: per face position). ``src == dst`` is a cube looped onto itself.
Circuit = Tuple[int, int, int]

#: Sub-slice shapes GKE documents for dynamic sub-slicing (topologies smaller
#: than 4x4x4). Used as the default allowed list; a parameter, not a claim.
GKE_SUBCUBE_SHAPES: Tuple[Coord, ...] = ((2, 2, 1), (2, 2, 2), (2, 2, 4), (2, 4, 4))


@dataclass(frozen=True)
class OCSConfig:
    """The knobs. Every default is cited or labelled in docs/ocs-cubes.md."""

    #: Chips per cube along each axis. 4x4x4 is the public TPU v4/GKE cube.
    geometry: Coord = (4, 4, 4)
    #: Usable ports per OCS. The TPU v4 Palomar switch is 136x136 with 128 in
    #: use and 8 kept for testing and repair (Jouppi et al., ISCA 2023).
    ocs_ports: int = 128
    #: Longest a stitched slice may be along any axis, in cubes. 4 matches the
    #: 16-chip axes of the static 16x16x16 pod this is compared against. None
    #: lifts the limit to the domain size.
    max_cubes_per_axis: Optional[int] = 4
    #: Whether stitching closes the ring on every axis. The OCS makes the ring
    #: available; it is still a circuit somebody has to configure.
    close_rings: bool = True
    #: Shapes a job smaller than a cube may take (any axis permutation).
    subcube_shapes: Tuple[Coord, ...] = GKE_SUBCUBE_SHAPES
    #: Whether a sub-slice that spans a whole cube axis gets that axis looped
    #: through the OCS. Not documented publicly, so off unless asked for.
    subcube_rings: bool = False

    def __post_init__(self) -> None:
        if len(self.geometry) < 1 or any(g < 1 for g in self.geometry):
            raise ValueError("cube geometry needs positive extents")
        if self.ocs_ports < 2 or self.ocs_ports % 2:
            raise ValueError("an OCS needs an even number of usable ports, at least 2")
        if self.max_cubes_per_axis is not None and self.max_cubes_per_axis < 1:
            raise ValueError("max_cubes_per_axis must be at least 1")
        for shape in self.subcube_shapes:
            if len(shape) != len(self.geometry):
                raise ValueError(f"sub-cube shape {shape} has the wrong rank")

    @property
    def ndim(self) -> int:
        return len(self.geometry)

    @property
    def cube_chips(self) -> int:
        return math.prod(self.geometry)

    def face_links(self, axis: int) -> int:
        """Links on one face perpendicular to ``axis``."""
        return math.prod(g for i, g in enumerate(self.geometry) if i != axis)

    @property
    def ocs_count(self) -> int:
        """One switch per (axis, face position). 48 for a 4x4x4 cube."""
        return sum(self.face_links(a) for a in range(self.ndim))

    @property
    def cubes_per_domain(self) -> int:
        """Each cube takes a + and a - port on every switch of its axis."""
        return self.ocs_ports // 2


# -- slices ------------------------------------------------------------------


@dataclass(frozen=True)
class StitchedSlice:
    """Whole cubes stitched into a rectangle of cubes."""

    job_id: str
    cube_shape: Coord
    #: Cube ids in row-major order over ``cube_shape``.
    cubes: Tuple[int, ...]
    circuits: FrozenSet[Circuit]
    geometry: Coord

    @property
    def chips(self) -> int:
        return len(self.cubes) * math.prod(self.geometry)

    @property
    def extents(self) -> Coord:
        return tuple(a * g for a, g in zip(self.cube_shape, self.geometry))

    def position(self, index: int) -> Coord:
        return _unravel(index, self.cube_shape)

    def cube_at(self, pos: Coord) -> int:
        return self.cubes[_ravel(pos, self.cube_shape)]

    def wraps(self) -> Tuple[bool, ...]:
        """Per axis: is every line along it closed by a configured circuit?

        Derived from :attr:`circuits` and nothing else. A slice whose closing
        circuit was not set up is a mesh in that axis, however many cubes it has.
        """
        out = []
        for axis, a in enumerate(self.cube_shape):
            closed = True
            for pos in _lines(self.cube_shape, axis):
                last = pos[:axis] + (a - 1,) + pos[axis + 1:]
                first = pos[:axis] + (0,) + pos[axis + 1:]
                if (axis, self.cube_at(last), self.cube_at(first)) not in self.circuits:
                    closed = False
                    break
            out.append(closed and self.extents[axis] >= 3)
        return tuple(out)

    def topology(self) -> Topology:
        return Topology(self.extents, self.wraps())


@dataclass(frozen=True)
class SubSlice:
    """A job smaller than a cube, carved out of one cube."""

    job_id: str
    cube: int
    rect: SliceRect
    circuits: FrozenSet[Circuit]
    geometry: Coord

    @property
    def chips(self) -> int:
        return self.rect.chips

    def wraps(self) -> Tuple[bool, ...]:
        return tuple(
            (axis, self.cube, self.cube) in self.circuits and e == g and e >= 3
            for axis, (e, g) in enumerate(zip(self.rect.extent, self.geometry))
        )

    def topology(self) -> Topology:
        return Topology(tuple(self.rect.extent), self.wraps())


def stitch_circuits(cube_shape: Coord, cubes: Sequence[int], *,
                    close_rings: bool) -> FrozenSet[Circuit]:
    """The OCS bundles that make ``cubes`` one slice of shape ``cube_shape``.

    Neighbours along each line are joined ``+`` to ``-``. The ring is one more
    bundle per line, from the last cube back to the first, and exists only if
    ``close_rings`` asks for it --- including on an axis one cube long, where it
    loops the cube onto itself.
    """
    out: Set[Circuit] = set()
    for axis, a in enumerate(cube_shape):
        for pos in _lines(cube_shape, axis):
            line = [cubes[_ravel(pos[:axis] + (i,) + pos[axis + 1:], cube_shape)]
                    for i in range(a)]
            for i in range(a - 1):
                out.add((axis, line[i], line[i + 1]))
            if close_rings:
                out.add((axis, line[-1], line[0]))
    return frozenset(out)


def stitched_graph(s: StitchedSlice) -> Dict[Coord, List[Coord]]:
    """The chip graph of a stitched slice, built from its circuits only.

    Nodes are virtual coordinates (cube position times geometry plus the chip's
    place inside the cube). Inside a cube, chips are an electrical mesh. Between
    cubes, only a configured circuit carries a link. Nothing here consults
    :meth:`StitchedSlice.wraps`, so the registry can check one against the other.
    """
    g = s.geometry
    ndim = len(g)
    index = {cube: s.position(i) for i, cube in enumerate(s.cubes)}
    graph: Dict[Coord, List[Coord]] = {}
    for i, cube in enumerate(s.cubes):
        base = tuple(p * e for p, e in zip(index[cube], g))
        for local in itertools.product(*(range(e) for e in g)):
            node = tuple(b + l for b, l in zip(base, local))
            peers = graph.setdefault(node, [])
            for axis in range(ndim):
                for step in (-1, 1):
                    l2 = local[axis] + step
                    if 0 <= l2 < g[axis]:
                        peer = node[:axis] + (node[axis] + step,) + node[axis + 1:]
                        if peer not in peers:
                            peers.append(peer)
    for axis, src, dst in s.circuits:
        a_base = tuple(p * e for p, e in zip(index[src], g))
        b_base = tuple(p * e for p, e in zip(index[dst], g))
        for local in itertools.product(*(range(e) for e in g)):
            if local[axis] != g[axis] - 1:
                continue
            u = tuple(b + l for b, l in zip(a_base, local))
            far = local[:axis] + (0,) + local[axis + 1:]
            v = tuple(b + l for b, l in zip(b_base, far))
            if u == v:
                continue
            for x, y in ((u, v), (v, u)):
                if y not in graph[x]:
                    graph[x].append(y)
    return graph


def measured_diameter(graph: Dict[Coord, List[Coord]]) -> int:
    """Breadth-first search from every node. Small slices only."""
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
        if len(seen) != len(graph):
            raise ValueError("stitched slice is disconnected")
        worst = max(worst, max(seen.values()))
    return worst


# -- the pod ------------------------------------------------------------------


@dataclass
class OCSPod:
    """A set of cubes, the slices stitched from them, and the spare policy.

    ``spare_policy``:

    ``"borrow"``
        No cube is held back. A failed cube is swapped for any whole free
        healthy cube in its domain, if one exists. Costs nothing until the pod
        is full, then cannot help.
    ``"reserve"``
        The last ``spares`` cubes of each domain's id range are held out of
        placement and used only for swaps. Always helps until they run out, and
        costs ``spares`` cubes of admittable capacity whether or not anything
        fails.
    """

    n_cubes: int
    config: OCSConfig = field(default_factory=OCSConfig)
    spares: int = 0
    spare_policy: str = "borrow"
    stitched: Dict[str, StitchedSlice] = field(default_factory=dict)
    sub: Dict[str, SubSlice] = field(default_factory=dict)
    #: Per cube, the chips inside it that are out of service.
    unhealthy: Dict[int, Set[Coord]] = field(default_factory=dict)
    #: Cubes held for swaps (reserve policy). Filled in __post_init__.
    spare_pool: List[int] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.n_cubes < 1:
            raise ValueError("a pod needs at least one cube")
        if self.spare_policy not in ("borrow", "reserve"):
            raise ValueError("spare_policy must be 'borrow' or 'reserve'")
        if self.spares < 0 or self.spares >= self.n_cubes:
            raise ValueError("spares must be at least 0 and fewer than the cubes")
        if self.spare_policy == "reserve" and not self.spare_pool:
            self.spare_pool = list(range(self.n_cubes - self.spares, self.n_cubes))
        if self.spare_policy == "borrow" and self.spares:
            raise ValueError("the borrow policy holds no cubes back; spares must be 0")

    # -- structure -----------------------------------------------------------

    @property
    def chips(self) -> int:
        return self.n_cubes * self.config.cube_chips

    def domain(self, cube: int) -> int:
        return cube // self.config.cubes_per_domain

    def domains(self) -> List[List[int]]:
        out: Dict[int, List[int]] = {}
        for c in range(self.n_cubes):
            out.setdefault(self.domain(c), []).append(c)
        return [out[k] for k in sorted(out)]

    def owner(self, cube: int) -> Optional[str]:
        for s in self.stitched.values():
            if cube in s.cubes:
                return s.job_id
        return None

    def partial_cubes(self) -> Set[int]:
        return {s.cube for s in self.sub.values()}

    def is_whole_free(self, cube: int, *, include_spares: bool = False) -> bool:
        """Free for stitching: unowned, unshared, healthy, and not held back."""
        if not include_spares and cube in self.spare_pool:
            return False
        return (self.owner(cube) is None and cube not in self.partial_cubes()
                and not self.unhealthy.get(cube))

    def whole_free(self, domain_cubes: Sequence[int]) -> List[int]:
        return [c for c in domain_cubes if self.is_whole_free(c)]

    # -- accounting ----------------------------------------------------------

    def allocated_chips(self) -> int:
        return (sum(s.chips for s in self.stitched.values())
                + sum(s.chips for s in self.sub.values()))

    def unhealthy_chips(self) -> int:
        return sum(len(v) for v in self.unhealthy.values())

    def free_chips(self) -> int:
        """Healthy chips nobody holds. Reserved spares count as free: they are
        what a free-chip report would show, and holding them back is part of
        the gap, not a different number."""
        held = set()
        for s in self.stitched.values():
            held.update(s.cubes)
        free = 0
        for c in range(self.n_cubes):
            if c in held:
                continue
            used = sum(s.chips for s in self.sub.values() if s.cube == c)
            free += self.config.cube_chips - used - len(self.unhealthy.get(c, ()))
        return free

    def cube_shapes(self, m: int, limit: int) -> Tuple[Coord, ...]:
        """Cube-count shapes for ``m`` cubes, compact first."""
        cap = self.config.max_cubes_per_axis or limit
        cap = min(cap, limit)
        if cap < 1:
            return ()
        box = Topology((cap,) * self.config.ndim, (False,) * self.config.ndim)
        return candidate_shapes(m, box)

    def subcube_candidates(self, chips: int) -> List[Coord]:
        """Allowed sub-cube shapes of this chip count that fit a cube."""
        g = self.config.geometry
        out: Set[Coord] = set()
        for shape in self.config.subcube_shapes:
            if math.prod(shape) != chips:
                continue
            for perm in set(itertools.permutations(shape)):
                if all(p <= e for p, e in zip(perm, g)):
                    out.add(perm)
        return sorted(out, key=lambda s: (sum(s), s))

    def shape_feasible(self, chips: int) -> bool:
        """Could this request be placed on an empty pod at all?"""
        cube = self.config.cube_chips
        if chips < cube:
            return bool(self.subcube_candidates(chips))
        if chips % cube:
            return False
        biggest = max(len(d) - (self.spares if self.spare_policy == "reserve" else 0)
                      for d in self.domains())
        return any(True for _ in self.cube_shapes(chips // cube, biggest)) \
            and chips // cube <= biggest

    # -- placement -----------------------------------------------------------

    def _cube_fabric(self, cube: int) -> Fabric:
        topo = Topology(self.config.geometry, (False,) * self.config.ndim)
        fab = Fabric(topo)
        for s in self.sub.values():
            if s.cube == cube:
                fab.allocations[s.job_id] = s.rect
        fab.unhealthy.update(self.unhealthy.get(cube, set()))
        return fab

    def place(self, job_id: str, chips: int):
        """Place a job. Raises :class:`NoPlacement` when it cannot."""
        if job_id in self.stitched or job_id in self.sub:
            raise ValueError(f"{job_id} is already placed")
        cube = self.config.cube_chips
        if chips < cube:
            return self._place_sub(job_id, chips)
        if chips % cube:
            raise NoPlacement(
                f"{job_id}: {chips} chips is not a whole number of {cube}-chip "
                "cubes; refused rather than rounded (ASSUMPTIONS A7)")
        return self._place_stitched(job_id, chips // cube)

    def _place_stitched(self, job_id: str, m: int) -> StitchedSlice:
        options = []
        for d, members in enumerate(self.domains()):
            free = self.whole_free(members)
            if len(free) >= m:
                options.append((len(free), d, free))
        if not options:
            raise NoPlacement(f"{job_id}: no domain has {m} whole free cubes")
        # best fit: the domain with the fewest free cubes that still suffices
        _, d, free = min(options)
        shapes = self.cube_shapes(m, len(self.domains()[d]))
        if not shapes:
            raise NoPlacement(f"{job_id}: {m} cubes have no shape within "
                              f"{self.config.max_cubes_per_axis} cubes per axis")
        shape = shapes[0]
        cubes = tuple(free[:m])
        s = StitchedSlice(job_id, shape, cubes,
                          stitch_circuits(shape, cubes, close_rings=self.config.close_rings),
                          self.config.geometry)
        self.stitched[job_id] = s
        return s

    def _place_sub(self, job_id: str, chips: int) -> SubSlice:
        shapes = self.subcube_candidates(chips)
        if not shapes:
            raise NoPlacement(f"{job_id}: no allowed sub-cube shape holds {chips} chips")
        for cube in self._subcube_hosts():
            fab = self._cube_fabric(cube)
            for shape in shapes:
                try:
                    rect = fab.place(Request(job_id=job_id, chips=chips, shape=shape))
                except NoPlacement:
                    continue
                circuits = frozenset(
                    (axis, cube, cube) for axis, (e, g) in
                    enumerate(zip(rect.extent, self.config.geometry))
                    if self.config.subcube_rings and e == g)
                s = SubSlice(job_id, cube, rect, circuits, self.config.geometry)
                self.sub[job_id] = s
                return s
        raise NoPlacement(f"{job_id}: no cube has room for {chips} chips")

    def _subcube_hosts(self) -> List[int]:
        """Where a sub-cube job may go, in order: cubes already shared (fullest
        first, so small jobs pack together and leave whole cubes whole), then
        one fresh cube."""
        partial = sorted(self.partial_cubes() - set(self.spare_pool),
                         key=lambda c: (-sum(s.chips for s in self.sub.values()
                                             if s.cube == c), c))
        fresh = [c for c in range(self.n_cubes) if self.is_whole_free(c)]
        return partial + fresh[:1]

    def release(self, job_id: str) -> None:
        if job_id in self.stitched:
            del self.stitched[job_id]
        elif job_id in self.sub:
            del self.sub[job_id]
        else:
            raise KeyError(job_id)

    # -- what is left --------------------------------------------------------

    def largest_placeable(self) -> int:
        """The biggest single job that could be placed right now, in chips."""
        cube = self.config.cube_chips
        best = 0
        for members in self.domains():
            free = len(self.whole_free(members))
            for m in range(free, 0, -1):
                if self.cube_shapes(m, len(members)):
                    best = max(best, m * cube)
                    break
        if best:
            return best
        sizes = sorted({math.prod(s) for s in self.config.subcube_shapes}, reverse=True)
        candidates = sorted(self.partial_cubes() - set(self.spare_pool))
        for size in sizes:
            for c in candidates:
                fab = self._cube_fabric(c)
                if any(any(fab.is_free(r) for r in fab.positions(shape))
                       for shape in self.subcube_candidates(size)):
                    return size
        return 0

    # -- failure -------------------------------------------------------------

    def fail(self, cube: int, local: Coord) -> None:
        if not 0 <= cube < self.n_cubes:
            raise ValueError(f"cube {cube} is not in this pod")
        if len(local) != self.config.ndim or any(
                not 0 <= x < g for x, g in zip(local, self.config.geometry)):
            raise ValueError(f"{local} is not a chip in a cube")
        self.unhealthy.setdefault(cube, set()).add(tuple(local))

    def copy(self) -> "OCSPod":
        return OCSPod(self.n_cubes, self.config, self.spares, self.spare_policy,
                      dict(self.stitched), dict(self.sub),
                      {k: set(v) for k, v in self.unhealthy.items()},
                      list(self.spare_pool))

    def swap_target(self, job_id: str, failed_cube: int) -> Optional[int]:
        """A healthy whole cube in the same domain to replace ``failed_cube``."""
        d = self.domain(failed_cube)
        pool = [c for c in self.spare_pool if self.domain(c) == d
                and self.is_whole_free(c, include_spares=True)]
        if self.spare_policy == "reserve":
            return pool[0] if pool else None
        free = [c for c in self.domains()[d] if self.is_whole_free(c)]
        return free[0] if free else None

    def recover(self, job_id: str, failed_cube: int, local: Coord) -> "Recovery":
        """Every way back for a stitched slice after one chip dies.

        ``swap``: replace the whole failed cube with a healthy one and re-stitch
        the same shape --- nothing lost from the job, the checkpoint restores,
        one cube of pod capacity consumed (its other chips idle until repair).
        ``restitch``: drop to the largest legal cube count without the failed
        cube --- rings re-closed, shape changed.
        ``cordon``: the static answer, pulling a chip face in on the stitched
        rectangle --- location-dependent, and the axis it shrinks loses its ring.
        """
        s = self.stitched[job_id]
        if failed_cube not in s.cubes:
            raise ValueError(f"cube {failed_cube} is not part of {job_id}")
        pos = s.position(s.cubes.index(failed_cube))
        virtual = tuple(p * g + l for p, g, l in zip(pos, s.geometry, local))
        rect = SliceRect((0,) * len(s.extents), s.extents)
        shrink = cheapest_shrink(rect, virtual)
        cordon_lost = shrink.chips_lost if shrink.rect is not None else s.chips
        cordon_wraps = None
        if shrink.rect is not None:
            cordon_wraps = tuple(w and e == t for w, e, t
                                 in zip(s.wraps(), shrink.rect.extent, s.extents))

        m = len(s.cubes)
        limit = len(self.domains()[self.domain(failed_cube)])
        restitch_cubes = 0
        for k in range(m - 1, 0, -1):
            if self.cube_shapes(k, limit):
                restitch_cubes = k
                break
        restitch_lost = s.chips - restitch_cubes * self.config.cube_chips

        target = self.swap_target(job_id, failed_cube)
        return Recovery(
            job_id=job_id, chips=s.chips, failed_cube=failed_cube,
            swap_cube=target,
            restitch_chips_lost=restitch_lost,
            cordon_chips_lost=cordon_lost,
            cordon_wraps=cordon_wraps,
            stranded_on_swap=self.config.cube_chips - 1 if target is not None else 0,
        )

    def apply_swap(self, job_id: str, failed_cube: int, local: Coord) -> StitchedSlice:
        """Mark the chip failed and replace its cube; the shape is unchanged."""
        target = self.swap_target(job_id, failed_cube)
        if target is None:
            raise NoPlacement(f"{job_id}: no healthy cube to swap in")
        self.fail(failed_cube, local)
        s = self.stitched[job_id]
        cubes = tuple(target if c == failed_cube else c for c in s.cubes)
        circuits = stitch_circuits(s.cube_shape, cubes,
                                   close_rings=self.config.close_rings)
        new = StitchedSlice(job_id, s.cube_shape, cubes, circuits, s.geometry)
        self.stitched[job_id] = new
        if target in self.spare_pool:
            self.spare_pool.remove(target)
        return new

    # -- invariants the registry checks ------------------------------------

    def port_usage(self) -> Dict[Tuple[int, int, int], int]:
        """Ports in use on each OCS, keyed (domain, axis, face position).

        Every bundle uses one ``+`` port and one ``-`` port on each switch of its
        axis. Raises if any cube face is used twice --- a port can carry one
        circuit.
        """
        used: Dict[Tuple[int, int, int], int] = {}
        taken: Set[Tuple[int, int, str]] = set()
        bundles: List[Circuit] = []
        for s in self.stitched.values():
            bundles.extend(s.circuits)
        for s in self.sub.values():
            bundles.extend(s.circuits)
        for axis, src, dst in bundles:
            if self.domain(src) != self.domain(dst):
                raise ValueError(f"circuit {axis},{src}->{dst} crosses a domain")
            for port in ((axis, src, "+"), (axis, dst, "-")):
                if port in taken and not _shared_subcube_face(self, axis, src, dst):
                    raise ValueError(f"port {port} carries two circuits")
                taken.add(port)
            for p in range(self.config.face_links(axis)):
                key = (self.domain(src), axis, p)
                used[key] = used.get(key, 0) + 2
        return used


def _shared_subcube_face(pod: OCSPod, axis: int, src: int, dst: int) -> bool:
    """Sub-slices that loop the same cube face use disjoint face positions."""
    return src == dst and src in pod.partial_cubes()


@dataclass(frozen=True)
class Recovery:
    job_id: str
    chips: int
    failed_cube: int
    swap_cube: Optional[int]
    restitch_chips_lost: int
    cordon_chips_lost: int
    cordon_wraps: Optional[Tuple[bool, ...]]
    stranded_on_swap: int

    @property
    def can_swap(self) -> bool:
        return self.swap_cube is not None

    def best_without_spare(self) -> Tuple[str, int]:
        if self.restitch_chips_lost < self.cordon_chips_lost:
            return "restitch", self.restitch_chips_lost
        return "cordon", self.cordon_chips_lost

    def best(self) -> Tuple[str, int]:
        if self.can_swap:
            return "swap", 0
        return self.best_without_spare()


# -- helpers --------------------------------------------------------------------


def _ravel(pos: Coord, shape: Coord) -> int:
    idx = 0
    for p, s in zip(pos, shape):
        idx = idx * s + p
    return idx


def _unravel(index: int, shape: Coord) -> Coord:
    out = []
    for s in reversed(shape):
        out.append(index % s)
        index //= s
    return tuple(reversed(out))


def _lines(shape: Coord, axis: int):
    """One position per line along ``axis`` (with that axis set to 0)."""
    ranges = [range(1) if i == axis else range(s) for i, s in enumerate(shape)]
    return itertools.product(*ranges)


def pod_like_static(k_cubes_per_axis: int = 4, config: Optional[OCSConfig] = None,
                    **kw) -> OCSPod:
    """An OCS pod with the same chip count as a static ``(k*g)``-ary cube."""
    cfg = config or OCSConfig()
    return OCSPod(k_cubes_per_axis ** cfg.ndim, cfg, **kw)
