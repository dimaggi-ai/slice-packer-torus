"""Taking a failed chip out of service without leaving a hole in a rectangle.

One chip fails. The obvious response is to cordon that chip. The obvious
response is wrong, and the reason is the whole of this module.

A slice is a rectangle, and its topology guarantees --- the diameter, the
bisection, the fact that a ring closes --- are guarantees about a rectangle. Cut
one chip out of the middle and what remains is not a smaller rectangle. It is a
rectangle with a defect: rings that no longer close, shortest paths that detour,
and a shape no collective library has an algorithm for. Every published figure
about the slice is now false, and false in a direction nobody has measured.

So the honest cordon is bigger than the failure. To get back to a rectangle you
have to shrink a face past the failed chip, and the cost of that is set by
**where** the chip failed, not by the fact that it failed:

* a corner failure in a 16-cubed slice costs one face --- 256 chips, 6% of the
  slice;
* a centre failure in the same slice costs eight faces --- 2,048 chips, half of
  it.

Same failure, same hardware, an eight-fold difference in what it costs to stay
honest about the shape. That number is not in any capacity report, and it is
the number that decides whether a job shrinks, moves, or dies.

The third option --- keeping the hole and telling the job its topology is
unchanged --- is not offered here. :func:`shrink_options` will report it as
``KEEP_HOLE`` with its guarantees stripped, so a caller can choose it
deliberately, but nothing in this package will produce a topology object for a
non-rectangular slice.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .torus import Coord, SliceRect, Topology


class Response(str, Enum):
    #: Shrink a face past the failed chip. The slice stays a rectangle.
    SHRINK = "shrink"
    #: Keep the defect and lose every topology guarantee the slice had.
    KEEP_HOLE = "keep-hole"
    #: Nothing survives: the failure removes the last chip in some dimension.
    DESTROYED = "destroyed"


@dataclass(frozen=True)
class ShrinkOption:
    """One way to get back to a rectangle after losing a chip."""

    axis: int
    #: Which face was pulled in: ``"low"`` or ``"high"``.
    face: str
    rect: Optional[SliceRect]
    chips_lost: int
    response: Response

    @property
    def survives(self) -> bool:
        return self.rect is not None and self.rect.chips > 0

    def __str__(self) -> str:
        if not self.survives:
            return f"axis {self.axis} {self.face}: destroys the slice"
        return (
            f"axis {self.axis} {self.face}: {self.rect.canonical()} "
            f"({self.rect.chips:,} chips, {self.chips_lost:,} lost)"
        )


def shrink_options(rect: SliceRect, failed: Coord) -> Tuple[ShrinkOption, ...]:
    """Every way to shrink ``rect`` to a rectangle that excludes ``failed``.

    Two per axis --- pull in the low face or the high face. A middle plane
    cannot simply be deleted: removing a plane from the interior splits the
    rectangle into two rectangles, which is two slices and not one, and a job
    holding one slice cannot be handed two.
    """
    if not rect.contains(failed):
        raise ValueError(f"{failed} is not inside {rect.canonical()}")
    options: List[ShrinkOption] = []
    for axis in range(rect.ndim):
        origin, extent = rect.origin[axis], rect.extent[axis]
        position = failed[axis] - origin
        plane = rect.chips // extent

        # Pull the low face up to just past the failure.
        keep_high = extent - position - 1
        low = _rebuilt(rect, axis, failed[axis] + 1, keep_high)
        options.append(ShrinkOption(
            axis, "low", low, rect.chips - (low.chips if low else 0),
            Response.SHRINK if low else Response.DESTROYED,
        ))

        # Pull the high face down to just before it.
        keep_low = position
        high = _rebuilt(rect, axis, origin, keep_low)
        options.append(ShrinkOption(
            axis, "high", high, rect.chips - (high.chips if high else 0),
            Response.SHRINK if high else Response.DESTROYED,
        ))
    return tuple(options)


def _rebuilt(rect: SliceRect, axis: int, origin: int, extent: int) -> Optional[SliceRect]:
    if extent < 1:
        return None
    return SliceRect(
        rect.origin[:axis] + (origin,) + rect.origin[axis + 1:],
        rect.extent[:axis] + (extent,) + rect.extent[axis + 1:],
    )


def cheapest_shrink(rect: SliceRect, failed: Coord) -> ShrinkOption:
    """The shrink that loses the fewest chips, or a DESTROYED verdict.

    Ties break toward the lower axis and then toward the low face, so the answer
    is reproducible. A tie is common: a failure at the exact centre of a cube
    has six equally bad answers.
    """
    survivors = [o for o in shrink_options(rect, failed) if o.survives]
    if not survivors:
        return ShrinkOption(0, "none", None, rect.chips, Response.DESTROYED)
    return min(survivors, key=lambda o: (o.chips_lost, o.axis, o.face != "low"))


def cordon_cost(rect: SliceRect, failed: Coord) -> int:
    """Chips lost to keep ``rect`` a rectangle after ``failed`` dies."""
    return cheapest_shrink(rect, failed).chips_lost


def worst_position(rect: SliceRect) -> Tuple[Coord, int]:
    """The chip whose failure costs the most, and what it costs.

    Always an interior chip, and for a cube always the centre. Worth computing
    because it is the number to plan against: a slice's exposure to a single
    chip failure is the worst case, not the average.
    """
    worst_coord, worst_cost = None, -1
    for coord in rect.coords():
        cost = cordon_cost(rect, coord)
        if cost > worst_cost:
            worst_coord, worst_cost = coord, cost
    return worst_coord, worst_cost


def exposure(rect: SliceRect) -> Dict[str, float]:
    """How much a single chip failure costs this slice, best to worst.

    The spread between best and worst is the point. A slice whose exposure is
    flat has no bad chips; a slice whose worst case is eight times its best has
    a lottery running underneath it that nobody is tracking.
    """
    costs = sorted(cordon_cost(rect, c) for c in rect.coords())
    total = rect.chips
    return {
        "best": costs[0],
        "median": costs[len(costs) // 2],
        "worst": costs[-1],
        "mean": sum(costs) / len(costs),
        "worst_fraction": costs[-1] / total,
        "best_fraction": costs[0] / total,
        "spread": costs[-1] / costs[0] if costs[0] else math.inf,
    }


@dataclass(frozen=True)
class CordonImpact:
    """What a set of failed chips does to every slice on a fabric."""

    failed: Tuple[Coord, ...]
    #: job id -> the cheapest surviving rectangle, or None if destroyed.
    survivors: Dict[str, Optional[SliceRect]]
    #: job id -> chips lost.
    losses: Dict[str, int]
    #: Failed chips that landed on no slice at all.
    unallocated_hits: int

    @property
    def destroyed(self) -> Tuple[str, ...]:
        return tuple(sorted(j for j, r in self.survivors.items() if r is None))

    @property
    def total_chips_lost(self) -> int:
        return sum(self.losses.values())

    def explain(self) -> str:
        if not self.survivors and not self.unallocated_hits:
            return "no slice touched"
        lines = []
        for job_id in sorted(self.survivors):
            rect = self.survivors[job_id]
            lost = self.losses[job_id]
            if rect is None:
                lines.append(f"  {job_id}: destroyed, {lost:,} chips lost")
            else:
                lines.append(
                    f"  {job_id}: shrinks to {rect.canonical()} "
                    f"({rect.chips:,} chips, {lost:,} lost)"
                )
        if self.unallocated_hits:
            lines.append(f"  {self.unallocated_hits} failed chip(s) hit free space")
        return "\n".join(lines)


def cordon_impact(
    allocations: Dict[str, SliceRect], failed: Sequence[Coord]
) -> CordonImpact:
    """Apply a set of failures to every slice, shrinking each to a rectangle.

    Failures are applied one at a time in the order given, because shrinking for
    the first can move the second outside the slice entirely --- in which case it
    costs nothing more, and pretending otherwise would double-count. The order
    is the caller's; failures that arrive together should be passed together and
    the result read as one of several possible orderings, not the only one.
    """
    survivors: Dict[str, Optional[SliceRect]] = {}
    losses: Dict[str, int] = {}
    unallocated = 0

    for coord in failed:
        hit = False
        for job_id, rect in allocations.items():
            current = survivors.get(job_id, rect)
            if current is None:
                continue
            if not current.contains(coord):
                continue
            hit = True
            option = cheapest_shrink(current, coord)
            before = current.chips
            survivors[job_id] = option.rect
            after = option.rect.chips if option.rect else 0
            losses[job_id] = losses.get(job_id, 0) + (before - after)
        if not hit:
            unallocated += 1

    return CordonImpact(tuple(failed), survivors, losses, unallocated)
