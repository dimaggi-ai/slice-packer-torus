"""Moving a job rather than shrinking it, and what each choice actually costs.

After a failure a job has two honest options, and they fail in opposite
directions:

**Shrink in place.** Cheap in hardware --- nothing moves, no other tenant is
touched --- and expensive in software. The logical rank grid changes shape, so a
checkpoint written by the old grid does not restore onto the new one without a
reshard, and the collective schedule the job was tuned for is gone.

**Re-embed at the same shape.** Expensive in hardware --- every chip in the job
changes physical identity, and on a busy fabric there is nowhere to put it
without evicting somebody --- and free in software. The logical grid is
untouched, so the checkpoint restores and the collective schedule still holds.

Capacity planners price the first and ignore the second, because the first
shows up as chips and the second shows up as a training run that will not
restart. This module prices both, and prices the third thing nobody prices: the
**drain cost**, the chips belonging to other jobs that have to be evicted before
a same-shape re-embed is even possible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .packing import Fabric, Request, candidate_shapes
from .torus import Coord, SliceRect, Topology

#: Above this many resident jobs, the exact drain search is refused rather than
#: quietly replaced by a greedy answer. See DECISIONS D3.
MAX_EXACT_DRAIN_VICTIMS = 16


@dataclass(frozen=True)
class Remap:
    """A proposed new home for a job, and what it costs to go there."""

    job_id: str
    before: SliceRect
    after: Optional[SliceRect]
    #: Chips whose physical coordinate changes. Zero only if nothing moved.
    chips_moved: int
    #: Chips the job no longer has.
    chips_lost: int
    #: True when the logical rank grid is unchanged, so a checkpoint restores.
    restore_compatible: bool
    #: Other jobs that must be evicted first.
    victims: Tuple[str, ...] = ()
    #: Chips belonging to those victims.
    drain_chips: int = 0

    @property
    def feasible(self) -> bool:
        return self.after is not None

    @property
    def touches_other_tenants(self) -> bool:
        return bool(self.victims)

    def explain(self) -> str:
        if self.after is None:
            return f"{self.job_id}: no placement"
        head = (
            f"{self.job_id}: {self.before.canonical()} -> {self.after.canonical()}"
            f"  moved {self.chips_moved:,}  lost {self.chips_lost:,}"
        )
        tail = "restores from checkpoint" if self.restore_compatible else "needs a reshard"
        if self.victims:
            tail += f"; evicts {', '.join(self.victims)} ({self.drain_chips:,} chips)"
        return f"{head}  [{tail}]"


def _remap(
    job_id: str,
    before: SliceRect,
    after: Optional[SliceRect],
    *,
    victims: Sequence[str] = (),
    drain_chips: int = 0,
) -> Remap:
    if after is None:
        return Remap(job_id, before, None, 0, before.chips, False)
    same_ground = set(after.coords()) & set(before.coords())
    moved = after.chips - len(same_ground)
    return Remap(
        job_id=job_id,
        before=before,
        after=after,
        chips_moved=moved,
        chips_lost=max(0, before.chips - after.chips),
        restore_compatible=after.extent == before.extent,
        victims=tuple(victims),
        drain_chips=drain_chips,
    )


def reembed_same_shape(fabric: Fabric, job_id: str) -> Remap:
    """Find somewhere else on healthy free ground with the identical shape.

    The job's own current ground counts as free, because it is being vacated ---
    but a placement that overlaps the old one is still a move for every chip
    that changes coordinate, and a placement identical to the old one is not a
    remedy at all and is refused.
    """
    before = fabric.allocations[job_id]
    trial = fabric.without(job_id)
    for candidate in trial.free_positions(before.extent):
        if candidate.canonical() == before.canonical():
            continue
        return _remap(job_id, before, candidate)
    return _remap(job_id, before, None)


def reembed_smaller(fabric: Fabric, job_id: str, chips: int) -> Remap:
    """Place the job somewhere at a smaller size, best network shape first."""
    before = fabric.allocations[job_id]
    trial = fabric.without(job_id)
    for shape in candidate_shapes(chips, fabric.pod):
        for candidate in trial.free_positions(shape):
            return _remap(job_id, before, candidate)
    return _remap(job_id, before, None)


def drain_plan(
    fabric: Fabric,
    job_id: str,
    *,
    shape: Optional[Tuple[int, ...]] = None,
    protected: Sequence[str] = (),
) -> Remap:
    """The cheapest set of evictions that makes room for a same-shape re-embed.

    Exact over subsets of the resident jobs, smallest total chips first, so the
    answer is the cheapest drain and not merely a drain. Refused above
    :data:`MAX_EXACT_DRAIN_VICTIMS` residents rather than silently downgraded to
    a greedy search --- a greedy drain that evicts one large tenant when two small
    ones would do is exactly the mistake this is meant to catch.
    """
    before = fabric.allocations[job_id]
    want = shape if shape is not None else before.extent

    base = fabric.without(job_id)
    others = [j for j in base.allocations if j not in set(protected)]
    if len(others) > MAX_EXACT_DRAIN_VICTIMS:
        raise ValueError(
            f"{len(others)} resident jobs exceeds the exact drain limit of "
            f"{MAX_EXACT_DRAIN_VICTIMS}; refusing rather than guessing"
        )

    for size in range(0, len(others) + 1):
        best: Optional[Remap] = None
        for victims in combinations(others, size):
            drained = sum(base.allocations[v].chips for v in victims)
            if best is not None and drained >= best.drain_chips:
                continue
            trial = base.without(*victims)
            for candidate in trial.free_positions(want):
                if size == 0 and candidate.canonical() == before.canonical():
                    continue
                best = _remap(job_id, before, candidate, victims=victims, drain_chips=drained)
                break
        if best is not None:
            return best
    return _remap(job_id, before, None)


def options(
    fabric: Fabric,
    job_id: str,
    failed: Coord,
    *,
    protected: Sequence[str] = (),
) -> Tuple[Remap, ...]:
    """Every honest response to one chip failing under ``job_id``, priced.

    Ordered as written, not by cost, because the ordering *is* a claim and a
    caller should see the claim rather than inherit it: shrink first because it
    touches nobody else, then a same-shape move, then a move that costs other
    tenants. :func:`slicepacker.reconstitute.plan` is where they get ranked.
    """
    from .cordon import cheapest_shrink

    before = fabric.allocations[job_id]
    out: List[Remap] = []

    shrunk = cheapest_shrink(before, failed)
    out.append(_remap(job_id, before, shrunk.rect))

    same = reembed_same_shape(fabric.cordon(failed), job_id)
    out.append(same)

    if not same.feasible:
        out.append(drain_plan(fabric.cordon(failed), job_id, protected=protected))

    return tuple(out)
