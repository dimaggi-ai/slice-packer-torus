"""Deciding what to do after a chip dies, and who is allowed to decide it.

Every option here is already priced by :mod:`slicepacker.embed`. What this
module adds is the second question, which is the one that actually delays
recovery in production: *may the control plane do this on its own, or does it
need a person?*

The rule used here is narrow on purpose. An action is autonomous (**L1**) only
when it is confined to the job that suffered the failure --- no other tenant's
chips change state --- and stays inside a declared bound. Everything that
reaches across a tenant boundary is **L0**: the planner may propose it, and a
person approves it. That is not a safety ritual. Evicting a neighbour to heal
your own job is a decision with a bill attached to somebody who is not in the
room, and no bound on blast radius makes it not that.

The output nobody else prints is :attr:`Reconstitution.cost_of_waiting`: the
difference between the best action available right now without a human and the
best action available at all. When that number is zero, waiting for approval
costs nothing and the escalation is free. When it is large, the approval queue
is the outage.

Ranking is lexicographic and the order is a **policy choice, not a fact**:
fewest tenants disturbed, then no reshard, then fewest chips lost, then fewest
chips moved. :func:`rank` takes an explicit key so a site that disagrees can say
so in code rather than by patching this file.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .cordon import Response, cheapest_shrink
from .embed import Remap, drain_plan, reembed_same_shape, reembed_smaller
from .packing import Fabric
from .torus import Coord, SliceRect


class Kind(str, Enum):
    SHRINK = "shrink-in-place"
    MOVE = "move-same-shape"
    DRAIN = "drain-then-move"
    NOTHING = "no-legal-action"


class Autonomy(str, Enum):
    #: The control plane may do this itself.
    L1 = "L1"
    #: A person approves it first.
    L0 = "L0"


@dataclass(frozen=True)
class Policy:
    """The bound inside which the control plane may act without asking."""

    #: Largest fraction of its own chips a job may lose autonomously.
    max_self_loss_fraction: float = 0.25
    #: May an autonomous action change the rank grid (forcing a reshard)?
    allow_reshard: bool = False
    #: May any action evict another tenant, even with approval?
    allow_eviction: bool = True
    #: Largest number of chips an autonomous action may move.
    max_chips_moved: int = 1 << 30

    def __post_init__(self) -> None:
        if not 0.0 <= self.max_self_loss_fraction <= 1.0:
            raise ValueError("max_self_loss_fraction is a fraction")


@dataclass(frozen=True)
class Candidate:
    kind: Kind
    remap: Remap
    autonomy: Autonomy
    #: Empty when the action is permitted at all; otherwise why it is not.
    blocked_by: Tuple[str, ...] = ()

    @property
    def legal(self) -> bool:
        return not self.blocked_by and self.remap.feasible

    @property
    def tenants_disturbed(self) -> int:
        return len(self.remap.victims)

    def sort_key(self) -> Tuple[int, int, int, int]:
        r = self.remap
        return (len(r.victims), 0 if r.restore_compatible else 1,
                r.chips_lost, r.chips_moved)

    def explain(self) -> str:
        mark = self.autonomy.value if self.legal else "--"
        line = f"[{mark}] {self.kind.value:<18} {self.remap.explain()}"
        if self.blocked_by:
            line += "\n       blocked: " + "; ".join(self.blocked_by)
        return line


def rank(
    candidates: Sequence[Candidate],
    key: Optional[Callable[[Candidate], object]] = None,
) -> Tuple[Candidate, ...]:
    """Order candidates cheapest-first under a stated key."""
    return tuple(sorted(candidates, key=key or Candidate.sort_key))


def _classify(kind: Kind, remap: Remap, policy: Policy, job_chips: int) -> Candidate:
    blocked: List[str] = []
    if not remap.feasible:
        return Candidate(kind, remap, Autonomy.L0, ("no placement exists",))

    if remap.victims and not policy.allow_eviction:
        blocked.append(f"evicts {len(remap.victims)} tenant(s) and eviction is off")

    autonomy = Autonomy.L1
    reasons: List[str] = []
    if remap.victims:
        autonomy = Autonomy.L0
        reasons.append("crosses a tenant boundary")
    loss_fraction = remap.chips_lost / job_chips if job_chips else 0.0
    if loss_fraction > policy.max_self_loss_fraction:
        autonomy = Autonomy.L0
        reasons.append(f"loses {loss_fraction * 100:.0f}% of the job, "
                       f"over the {policy.max_self_loss_fraction * 100:.0f}% bound")
    if not remap.restore_compatible and not policy.allow_reshard:
        autonomy = Autonomy.L0
        reasons.append("changes the rank grid, forcing a reshard")
    if remap.chips_moved > policy.max_chips_moved:
        autonomy = Autonomy.L0
        reasons.append(f"moves {remap.chips_moved:,} chips, over the "
                       f"{policy.max_chips_moved:,} bound")

    return Candidate(kind, remap, autonomy, tuple(blocked))


@dataclass(frozen=True)
class Reconstitution:
    """What to do about one failure, and who has to say yes."""

    job_id: str
    failed: Coord
    candidates: Tuple[Candidate, ...]
    best: Optional[Candidate]
    best_autonomous: Optional[Candidate]

    @property
    def verdict(self) -> str:
        if self.best is None:
            return "REFUSE"
        return "ACT" if self.best.autonomy is Autonomy.L1 else "PROPOSE"

    @property
    def needs_human(self) -> bool:
        return self.verdict == "PROPOSE"

    @property
    def cost_of_waiting(self) -> Optional[Dict[str, int]]:
        """What the job gives up by taking the L1 action instead of the best one.

        ``None`` when there is no autonomous action at all --- a different
        situation from a free wait, and one that must not be reported as zero.
        """
        if self.best is None or self.best_autonomous is None:
            return None
        a, b = self.best_autonomous.remap, self.best.remap
        return {
            "chips_lost": a.chips_lost - b.chips_lost,
            "chips_moved": a.chips_moved - b.chips_moved,
            "reshard": int(not a.restore_compatible) - int(not b.restore_compatible),
        }

    def explain(self) -> str:
        lines = [f"{self.job_id}: chip {self.failed} failed -> {self.verdict}"]
        for c in self.candidates:
            lines.append("  " + c.explain().replace("\n", "\n  "))
        if self.best is None:
            lines.append("  no legal action: the job cannot be reconstituted here")
            return "\n".join(lines)
        lines.append(f"  chosen: {self.best.kind.value} ({self.best.autonomy.value})")
        waiting = self.cost_of_waiting
        if waiting is None:
            lines.append("  no autonomous action exists; recovery waits on a person")
        elif not any(waiting.values()):
            lines.append("  waiting for approval costs nothing: the best action is L1")
        else:
            lines.append(
                f"  acting without a human instead costs "
                f"{waiting['chips_lost']:+,} chips lost, "
                f"{waiting['chips_moved']:+,} moved"
                + (", and a reshard" if waiting["reshard"] > 0 else "")
            )
        return "\n".join(lines)


def plan(
    fabric: Fabric,
    job_id: str,
    failed: Coord,
    *,
    policy: Policy = Policy(),
    protected: Sequence[str] = (),
    key: Optional[Callable[[Candidate], object]] = None,
) -> Reconstitution:
    """Enumerate, classify and rank every response to one chip failing.

    ``fabric`` is not modified. The caller applies whichever candidate it (or a
    person) accepts, which keeps the decision and the mutation in different
    places on purpose --- a planner that has already acted cannot be reviewed.
    """
    if job_id not in fabric.allocations:
        raise KeyError(job_id)
    before = fabric.allocations[job_id]
    if not before.contains(failed):
        raise ValueError(f"{failed} is not inside {job_id}'s slice {before.canonical()}")

    cordoned = fabric.cordon(failed)
    candidates: List[Candidate] = []

    shrunk = cheapest_shrink(before, failed)
    candidates.append(_classify(
        Kind.SHRINK,
        Remap(job_id, before, shrunk.rect,
              0, shrunk.chips_lost,
              shrunk.rect is not None and shrunk.rect.extent == before.extent),
        policy, before.chips,
    ))

    same = reembed_same_shape(cordoned, job_id)
    candidates.append(_classify(Kind.MOVE, same, policy, before.chips))

    if not same.feasible and policy.allow_eviction:
        try:
            drained = drain_plan(cordoned, job_id, protected=protected)
        except ValueError as exc:
            drained = Remap(job_id, before, None, 0, before.chips, False)
            candidates.append(Candidate(Kind.DRAIN, drained, Autonomy.L0, (str(exc),)))
        else:
            candidates.append(_classify(Kind.DRAIN, drained, policy, before.chips))

    ordered = rank(candidates, key)
    legal = [c for c in ordered if c.legal]
    best = legal[0] if legal else None
    autonomous = [c for c in legal if c.autonomy is Autonomy.L1]
    return Reconstitution(job_id, failed, ordered, best,
                          autonomous[0] if autonomous else None)
