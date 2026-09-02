"""Keeping tenants out of each other's blast radius, and what that costs.

A blast domain is a set of chips that leave service together: a rack on one
breaker, a row behind one CDU, a cage a technician opens. Isolation means two
tenants never share one --- so that a maintenance window, a breaker trip or a
coolant fault is one tenant's bad afternoon rather than two.

The cost of that is fragmentation, and it is measurable. But the sharper result
in this module is a conflict nobody writes down:

    **A job that wants a full wraparound dimension cannot be isolated in that
    dimension.**

A ring closes only if the slice spans the axis completely, and spanning the
axis completely means touching every blast domain along it. So "give me a
torus" and "keep me off other tenants' hardware" are not two requests that
happen to compete for space --- past a certain size they are contradictory, and
a scheduler that accepts both is going to silently drop one. :func:`conflicts`
names which.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Iterable, List, Optional, Sequence, Set, Tuple

from .packing import Fabric, NoPlacement, Request, candidate_shapes, shape_report
from .torus import Coord, SliceRect, Topology


@dataclass(frozen=True)
class Domains:
    """A partition of the pod into blast domains along one axis.

    ``width`` chips of that axis per domain. A rack is typically one value of
    one axis (``width=1``); a row is several.
    """

    axis: int
    width: int = 1
    label: str = "rack"

    def __post_init__(self) -> None:
        if self.width < 1:
            raise ValueError("a blast domain spans at least one chip")

    def of(self, coord: Coord) -> int:
        return coord[self.axis] // self.width

    def of_rect(self, rect: SliceRect) -> FrozenSet[int]:
        lo = rect.origin[self.axis]
        hi = lo + rect.extent[self.axis] - 1
        return frozenset(range(lo // self.width, hi // self.width + 1))

    def count(self, pod: Topology) -> int:
        return -(-pod.extents[self.axis] // self.width)

    def spans_all(self, rect: SliceRect, pod: Topology) -> bool:
        return len(self.of_rect(rect)) == self.count(pod)


@dataclass(frozen=True)
class Policy:
    """What isolation this fabric promises."""

    #: No two tenants may share a blast domain.
    dedicated_domains: bool = True
    #: Tenants may not be placed in touching domains (a technician's reach).
    domain_gap: int = 0

    def forbidden(self, mine: FrozenSet[int], theirs: FrozenSet[int]) -> bool:
        if self.dedicated_domains and (mine & theirs):
            return True
        if self.domain_gap:
            for a in mine:
                for b in theirs:
                    if 0 < abs(a - b) <= self.domain_gap:
                        return True
        return False


@dataclass(frozen=True)
class Violation:
    tenant_a: str
    tenant_b: str
    shared: Tuple[int, ...]

    def __str__(self) -> str:
        return (f"{self.tenant_a} and {self.tenant_b} share domain(s) "
                f"{', '.join(map(str, self.shared))}")


def tenant_domains(
    fabric: Fabric, domains: Domains, owners: Dict[str, str]
) -> Dict[str, FrozenSet[int]]:
    """Which blast domains each tenant currently occupies."""
    out: Dict[str, Set[int]] = {}
    for job_id, rect in fabric.allocations.items():
        tenant = owners.get(job_id, job_id)
        out.setdefault(tenant, set()).update(domains.of_rect(rect))
    return {t: frozenset(d) for t, d in out.items()}


def violations(
    fabric: Fabric,
    domains: Domains,
    owners: Dict[str, str],
    policy: Policy = Policy(),
) -> Tuple[Violation, ...]:
    """Every pair of tenants the current layout puts in each other's blast radius."""
    occupancy = tenant_domains(fabric, domains, owners)
    names = sorted(occupancy)
    out: List[Violation] = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if policy.forbidden(occupancy[a], occupancy[b]):
                out.append(Violation(a, b, tuple(sorted(occupancy[a] & occupancy[b]))))
    return tuple(out)


def conflicts(request: Request, pod: Topology, domains: Domains) -> Tuple[str, ...]:
    """Reasons this request cannot be both isolated and given what it asked for.

    Returned before any placement is attempted, because a contradiction in the
    request is not a capacity problem and should not be reported as one.
    """
    out: List[str] = []
    if request.min_torus_dims <= 0:
        return ()
    shapes = [s for s in candidate_shapes(request.chips, pod)
              if shape_report(s, pod)["torus_dims"] >= request.min_torus_dims]
    if not shapes:
        return (f"no shape of {request.chips} chips has {request.min_torus_dims} "
                f"wraparound dimension(s) in this pod",)
    if all(SliceRect((0,) * pod.ndim, s).extent[domains.axis] == pod.extents[domains.axis]
           for s in shapes):
        out.append(
            f"every shape with {request.min_torus_dims} wraparound dimension(s) spans "
            f"axis {domains.axis} completely, so it touches all "
            f"{domains.count(pod)} {domains.label}(s): isolation and wraparound "
            f"cannot both be honoured"
        )
    return tuple(out)


def isolated_positions(
    fabric: Fabric,
    shape: Coord,
    tenant: str,
    domains: Domains,
    owners: Dict[str, str],
    policy: Policy = Policy(),
) -> Iterable[SliceRect]:
    """Free positions of ``shape`` that keep ``tenant`` out of everyone's domains."""
    occupancy = tenant_domains(fabric, domains, owners)
    others = {t: d for t, d in occupancy.items() if t != tenant}
    for rect in fabric.free_positions(shape):
        mine = domains.of_rect(rect)
        if any(policy.forbidden(mine, theirs) for theirs in others.values()):
            continue
        yield rect


def place_isolated(
    fabric: Fabric,
    request: Request,
    domains: Domains,
    owners: Dict[str, str],
    policy: Policy = Policy(),
    *,
    objective: str = "diameter",
) -> SliceRect:
    """Place a request under an isolation policy, or raise :class:`NoPlacement`.

    Mutates ``fabric`` and ``owners`` on success, exactly as
    :meth:`Fabric.place` does, so the two can be used interchangeably.
    """
    tenant = request.tenant or request.job_id
    blockers = conflicts(request, fabric.pod, domains)
    if blockers:
        raise NoPlacement(f"{request.job_id}: " + "; ".join(blockers))

    from .packing import OBJECTIVES

    if request.shape is not None:
        shapes: Sequence[Coord] = (request.shape,)
    else:
        reports = [shape_report(s, fabric.pod)
                   for s in candidate_shapes(request.chips, fabric.pod)]
        reports = [r for r in reports if r["torus_dims"] >= request.min_torus_dims]
        shapes = [r["shape"] for r in sorted(reports, key=OBJECTIVES[objective])]

    for shape in shapes:
        for rect in isolated_positions(fabric, shape, tenant, domains, owners, policy):
            fabric.allocations[request.job_id] = rect
            owners[request.job_id] = tenant
            return rect
    raise NoPlacement(
        f"{request.job_id}: {request.chips} chips fit the pod but not the "
        f"isolation policy ({domains.label} width {domains.width}, "
        f"gap {policy.domain_gap})"
    )


@dataclass(frozen=True)
class IsolationCost:
    """What isolation cost this demand, in chips actually admitted."""

    admitted_open: int
    admitted_isolated: int
    chips_open: int
    chips_isolated: int
    refused: Tuple[str, ...]

    @property
    def chips_forgone(self) -> int:
        return self.chips_open - self.chips_isolated

    @property
    def fraction_forgone(self) -> float:
        return self.chips_forgone / self.chips_open if self.chips_open else 0.0

    def explain(self) -> str:
        return (
            f"open:     {self.admitted_open} job(s), {self.chips_open:,} chips\n"
            f"isolated: {self.admitted_isolated} job(s), {self.chips_isolated:,} chips\n"
            f"isolation forgoes {self.chips_forgone:,} chips "
            f"({self.fraction_forgone * 100:.0f}% of what the pod would have taken)"
            + (f"\nrefused under isolation: {', '.join(self.refused)}" if self.refused else "")
        )


def isolation_cost(
    pod: Topology,
    demand: Sequence[Request],
    domains: Domains,
    policy: Policy = Policy(),
) -> IsolationCost:
    """Admit the same demand twice --- open, then isolated --- and diff the result.

    Same arrival order both times, so the comparison isolates the policy and not
    the scheduler's luck. This is a lower bound on what isolation costs: a
    scheduler that knew the whole demand in advance could do better than
    first-fit at both ends, and would still not do better than open.
    """
    open_fab, iso_fab = Fabric(pod), Fabric(pod)
    owners: Dict[str, str] = {}
    admitted_open = admitted_iso = 0
    chips_open = chips_iso = 0
    refused: List[str] = []

    for request in demand:
        try:
            open_fab.place(request)
            admitted_open += 1
            chips_open += request.chips
        except NoPlacement:
            pass
        try:
            place_isolated(iso_fab, request, domains, owners, policy)
            admitted_iso += 1
            chips_iso += request.chips
        except NoPlacement:
            refused.append(request.job_id)

    return IsolationCost(admitted_open, admitted_iso, chips_open, chips_iso,
                         tuple(refused))
