#!/usr/bin/env python3
"""What this repository checks, and --- printed first --- what it does not.

Every point is one of three kinds, and the kind is the honest part:

``calibrated``
    Pinned to a figure published outside this work. Here that means the textbook
    closed forms for the k-ary n-cube. Read the first two declined items before
    treating these as strong: a closed form is a mathematical identity about an
    idealised topology, so agreement with it shows the code implements the model
    and shows nothing at all about any real pod. **This repository has no
    empirical anchor.**
``emergent``
    An ordering, a regime boundary or a distribution that nothing in the code
    was tuned to produce. These are the points that can actually go red on a
    real change.
``sanity``
    A property of this repository's own structure. Useful, and worth nothing as
    evidence about machines. Sanity points carry no citation, and the reference
    column prints ``-`` for them by construction.

Run it: ``python validation/validate_packing.py``. Exit status is 1 if any
point fails.
"""

from __future__ import annotations

import math
import random
import sys
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

sys.path.insert(0, "src")

from slicepacker.cordon import (  # noqa: E402
    cheapest_shrink,
    cordon_cost,
    cordon_impact,
    exposure,
    shrink_options,
)
from slicepacker.embed import drain_plan, reembed_same_shape  # noqa: E402
from slicepacker.packing import (  # noqa: E402
    Fabric,
    NoPlacement,
    Request,
    best_shape,
    candidate_shapes,
    shape_report,
)
from slicepacker.reconstitute import Autonomy  # noqa: E402
from slicepacker.reconstitute import plan as reconstitution_plan  # noqa: E402
from slicepacker.tenant import Domains, conflicts, isolation_cost, place_isolated  # noqa: E402
from slicepacker.tenant import Policy as IsolationPolicy  # noqa: E402
from slicepacker.tenant import violations  # noqa: E402
from slicepacker.torus import SliceRect, Topology  # noqa: E402

SEED = 20260902
#: Sample size for the randomised points. Sized so the whole registry runs in
#: seconds: the mutation suite reruns it once per mutation, and a registry that
#: is expensive to run is a registry that gets run less often.
POPULATION = 120

CALIBRATED, EMERGENT, SANITY = "calibrated", "emergent", "sanity"


@dataclass(frozen=True)
class Point:
    name: str
    kind: str
    passed: bool
    detail: str
    reference: str = "-"

    def __post_init__(self) -> None:
        if self.kind == SANITY and self.reference != "-":
            raise ValueError(
                f"{self.name}: a sanity point checks this repository's own structure "
                "and must not cite anything; a citation on it would make an internal "
                "consistency check look like evidence about the world"
            )
        if self.kind == CALIBRATED and self.reference == "-":
            raise ValueError(f"{self.name}: a calibrated point must name its anchor")


DECLINED: Tuple[str, ...] = (
    "No measured machine. Every number here is a model output. Nothing has been "
    "compared against a real torus pod, a real scheduler, or a real failure.",
    "The calibrated points pin textbook CLOSED FORMS, which are identities about "
    "an idealised k-ary n-cube. Agreeing with them shows this code implements the "
    "model correctly. It is not evidence that the model describes any machine, and "
    "this repository has no empirical anchor of any kind.",
    "Only chip failures are modelled. A failed LINK breaks a ring without removing "
    "a chip, and every shrink computed here would miss it entirely.",
    "Routing is not modelled. Diameter and bisection are static graph properties; "
    "what a collective actually achieves depends on the routing algorithm, deadlock "
    "avoidance, and the traffic pattern, none of which appear here.",
    "There is no time. Jobs in a real pod arrive and leave; every fragmentation "
    "figure here is a snapshot taken after one arrival order, not a steady state.",
    "Failures are independent and instantaneous. Correlated failure --- a breaker, a "
    "CDU, a technician --- is exactly what the blast-domain model is FOR, and nothing "
    "here generates it.",
    "The rectangle constraint is assumed, not derived. Schedulers that accept "
    "non-rectangular allocations exist; against those, every fragmentation number "
    "here is an upper bound rather than a measurement.",
    "Reshard cost is binary: the rank grid is either identical or it is not. A real "
    "reshard cost depends on the parallelism strategy and is not a step function.",
    "The L0/L1 boundary is a policy proposal. It is not a standard, nothing "
    "implements it, and a site that draws the line elsewhere is not wrong.",
    "Placement is first-fit. A smarter scheduler would fragment less, so the "
    "fragmentation figures describe first-fit and not the achievable minimum.",
    "A 'rack' here is a range of one coordinate. Real blast domains follow power, "
    "cooling and cabling, which do not have to line up with the network topology "
    "and frequently do not.",
    "Wraparound placement is refused by choice (ASSUMPTIONS A2). That costs packing "
    "efficiency, and the cost is not quantified anywhere in this repository.",
    "Chip counts that are not products of pod-dividing factors have no rectangle at "
    "all. Such a job is reported unplaceable, when in practice it would be rounded "
    "up; the rounding waste is not modelled.",
)


def rng() -> random.Random:
    return random.Random(SEED)


# -- calibrated -------------------------------------------------------------

DALLY = ("Dally, 'Performance analysis of k-ary n-cube interconnection networks', "
         "IEEE Trans. Computers 39(6), 1990; Duato, Yalamanchili & Ni, "
         "'Interconnection Networks', Morgan Kaufmann, 2003, ch. 1")

# (k, n, wrap, diameter, bisection) straight from the closed forms
# diameter = n*floor(k/2) torus, n*(k-1) mesh; bisection = 2k^(n-1) torus, k^(n-1) mesh
PUBLISHED = [
    (4, 2, True, 4, 8), (4, 2, False, 6, 4),
    (3, 2, True, 2, 6), (5, 2, True, 4, 10),
    (6, 2, False, 10, 6), (8, 2, True, 8, 16),
    (4, 3, True, 6, 32), (3, 3, True, 3, 18), (4, 3, False, 9, 16),
    (16, 3, True, 24, 512), (2, 4, False, 4, 8),
]


def point_diameter_matches_the_published_closed_form() -> Point:
    bad = [(k, n, w, Topology.cube(k, n, wrap=w).diameter(), d)
           for k, n, w, d, _ in PUBLISHED
           if Topology.cube(k, n, wrap=w).diameter() != d]
    return Point(
        "diameter-matches-the-published-closed-form", CALIBRATED, not bad,
        f"{len(PUBLISHED)} k-ary n-cubes, torus and mesh, agree with "
        f"n*floor(k/2) and n*(k-1)" + (f"; mismatches {bad}" if bad else ""),
        DALLY)


def point_bisection_matches_the_published_closed_form() -> Point:
    bad = [(k, n, w, Topology.cube(k, n, wrap=w).bisection_links(), b)
           for k, n, w, _, b in PUBLISHED
           if Topology.cube(k, n, wrap=w).bisection_links() != b]
    return Point(
        "bisection-matches-the-published-closed-form", CALIBRATED, not bad,
        f"{len(PUBLISHED)} k-ary n-cubes agree with 2k^(n-1) and k^(n-1)"
        + (f"; mismatches {bad}" if bad else ""),
        DALLY)


# -- emergent ---------------------------------------------------------------


def point_the_worst_single_chip_costs_exactly_half_the_slice() -> Point:
    """Shape-independent, which means packing cannot reduce it."""
    shapes = [(16, 16, 16), (4, 16, 64), (8, 8, 64), (1, 64, 64), (2, 32, 64),
              (64, 64), (32, 128), (8, 8, 8), (4, 4), (6, 10)]
    bad = []
    for shape in shapes:
        rect = SliceRect((0,) * len(shape), shape)
        if exposure(rect)["worst"] != rect.chips // 2:
            bad.append((shape, exposure(rect)["worst"], rect.chips // 2))
    return Point(
        "the-worst-single-chip-costs-exactly-half-the-slice", EMERGENT, not bad,
        f"over {len(shapes)} shapes the worst chip always costs chips/2; no shape "
        f"reduces the worst case, so packing cannot buy it down"
        + (f"; exceptions {bad}" if bad else ""))


def point_the_best_case_cordon_is_the_chip_count_over_the_longest_axis() -> Point:
    """An exact identity, and the reason compactness and survivability conflict.

    The cheapest way back to a rectangle is to pull in the nearest face, so the
    best case is one plane of the *largest* axis: ``chips // max(extent)``. A
    compact shape has no large axis, which is precisely what makes its typical
    failure expensive. The conflict with the network objectives is therefore not
    a coincidence to be observed --- it is a consequence to be derived, and it
    disappears wherever the compact shape already spans an axis.
    """
    pod = Topology.cube(64, 3)
    bad, conflicts_at, agrees_at = [], [], []
    for shape in ((16, 16, 16), (4, 16, 64), (8, 8, 64), (1, 64, 64), (2, 32, 64),
                  (8, 8, 8), (8, 16, 64), (6, 10), (32, 128)):
        rect = SliceRect((0,) * len(shape), shape)
        if exposure(rect)["best"] != rect.chips // max(shape):
            bad.append(shape)
    for chips in (512, 1024, 4096, 8192, 16384):
        compact = best_shape(chips, pod, objective="diameter")
        flat = best_shape(chips, pod, objective="torus_dims")
        if compact is None or flat is None or compact == flat:
            continue
        (conflicts_at if max(compact) < max(flat) else agrees_at).append(
            (chips, compact, flat))
    return Point(
        "the-best-case-cordon-is-the-chip-count-over-the-longest-axis", EMERGENT,
        not bad and bool(conflicts_at) and bool(agrees_at),
        f"the identity holds on 9 shapes; against it, the compact shape is the "
        f"more exposed one in {len(conflicts_at)} of "
        f"{len(conflicts_at) + len(agrees_at)} sizes where the objectives "
        f"disagree (e.g. {conflicts_at[0][0]:,} chips: "
        f"{'x'.join(map(str, conflicts_at[0][1]))} vs "
        f"{'x'.join(map(str, conflicts_at[0][2]))}), and NOT in "
        f"{len(agrees_at)} (e.g. {agrees_at[0][0]:,} chips, where the "
        f"diameter-optimal shape {'x'.join(map(str, agrees_at[0][1]))} already "
        f"spans an axis and so is no more exposed)"
        + (f"; identity broken on {bad}" if bad else ""))


def point_objective_disagreement_depends_on_the_pod() -> Point:
    """The demonstration is vacuous on a small pod. Measure where it is not."""
    sizes = [(8, 3), (16, 3), (32, 3), (64, 3), (128, 3)]
    disagree, tested = [], 0
    for k, n in sizes:
        pod = Topology.cube(k, n)
        for chips in (256, 512, 1024, 4096):
            if chips > pod.chips:
                continue
            picks = {o: best_shape(chips, pod, objective=o)
                     for o in ("diameter", "bisection", "torus_dims")}
            if any(v is None for v in picks.values()):
                continue
            tested += 1
            if len(set(picks.values())) > 1:
                disagree.append((k, chips))
    return Point(
        "objective-disagreement-depends-on-the-pod", EMERGENT,
        0 < len(disagree) < tested,
        f"the three objectives disagree in {len(disagree)} of {tested} "
        f"(pod, size) pairs --- neither always nor never, so a demonstration "
        f"built on one pod proves nothing; smallest disagreeing pod k="
        f"{min(k for k, _ in disagree) if disagree else '-'}")


def point_free_chips_overstate_what_a_pod_can_admit() -> Point:
    r = rng()
    pod = Topology.cube(16, 3)
    overstated, gaps, trials = 0, [], POPULATION
    for _ in range(trials):
        fabric = Fabric(pod)
        for i in range(r.randint(3, 8)):
            chips = r.choice([128, 256, 512, 1024])
            try:
                fabric.place(Request(job_id=f"j{i}", chips=chips))
            except NoPlacement:
                break
        free, placeable = fabric.free_chips(), fabric.largest_placeable()
        if placeable < free:
            overstated += 1
            gaps.append(1 - placeable / free)
    median = sorted(gaps)[len(gaps) // 2] if gaps else 0.0
    return Point(
        "free-chips-overstate-what-a-pod-can-admit", EMERGENT, overstated > 0,
        f"in {overstated} of {trials} random packings the free-chip count is larger "
        f"than the largest placeable job; median overstatement {median * 100:.0f}% "
        f"of free chips")


def point_isolation_costs_admitted_chips() -> Point:
    r = rng()
    pod = Topology.cube(16, 3)
    domains = Domains(axis=0)
    forgone, admitted = [], []
    for _ in range(24):
        demand = [Request(job_id=f"t{i}", chips=r.choice([64, 128, 256, 512]),
                          tenant=f"tenant-{i}") for i in range(10)]
        cost = isolation_cost(pod, demand, domains)
        forgone.append(cost.fraction_forgone)
        admitted.append(cost.admitted_isolated)
    positive = [f for f in forgone if f > 0]
    median = sorted(forgone)[len(forgone) // 2]
    # "Forgoes something" is also true of a policy that admits a single tenant
    # and refuses the rest, which is not isolation working but isolation
    # collapsing. The cost must be a cost, not a shutdown.
    workable = [a for a in admitted if a >= 2]
    return Point(
        "isolation-costs-admitted-chips", EMERGENT,
        bool(positive) and len(workable) == len(admitted),
        f"rack isolation forgoes chips in {len(positive)} of {len(forgone)} random "
        f"demands and still admits at least two tenants in {len(workable)} of "
        f"{len(admitted)}; median {median * 100:.0f}% of what the open pod would "
        f"have taken")


def point_a_full_torus_request_cannot_be_isolated() -> Point:
    """A contradiction in the request, not a capacity shortfall."""
    pod = Topology.cube(16, 3)
    contradictory = conflicts(
        Request(job_id="a", chips=4096, min_torus_dims=3), pod, Domains(axis=0))
    fine = conflicts(
        Request(job_id="b", chips=1024, min_torus_dims=2), pod, Domains(axis=0))
    return Point(
        "a-full-torus-request-cannot-be-isolated", EMERGENT,
        bool(contradictory) and not fine,
        "a request for 3 wraparound dimensions in a 16-cubed pod must span every "
        "rack, so isolation and wraparound are contradictory; a 2-dimension "
        "request at 1,024 chips is not")


def point_the_exact_drain_is_sometimes_cheaper_than_the_greedy_one() -> Point:
    """Evicting one big tenant when two small ones would do is the bug."""
    r = rng()
    pod = Topology.cube(8, 2)
    cheaper, contended = 0, 0
    for _ in range(POPULATION):
        fabric = Fabric(pod)
        placed = []
        for i in range(r.randint(3, 5)):
            chips = r.choice([8, 16, 24, 32])
            try:
                fabric.place(Request(job_id=f"j{i}", chips=chips))
                placed.append(f"j{i}")
            except NoPlacement:
                break
        if len(placed) < 3:
            continue
        victim = placed[0]
        if reembed_same_shape(fabric, victim).feasible:
            continue
        contended += 1
        try:
            exact = drain_plan(fabric, victim)
        except ValueError:
            continue
        if not exact.feasible:
            continue
        greedy = _greedy_drain(fabric, victim)
        if greedy is not None and exact.drain_chips < greedy:
            cheaper += 1
    return Point(
        "the-exact-drain-is-sometimes-cheaper-than-the-greedy-one", EMERGENT,
        cheaper > 0,
        f"in {cheaper} of {contended} contended cases the exact drain evicts fewer "
        f"chips than evicting the largest neighbour first --- a greedy planner "
        f"would have over-evicted")


def _greedy_drain(fabric: Fabric, job_id: str) -> Optional[int]:
    """Evict neighbours largest-first until the shape fits. The naive planner."""
    base = fabric.without(job_id)
    want = fabric.allocations[job_id].extent
    order = sorted(base.allocations, key=lambda j: -base.allocations[j].chips)
    drained, trial = 0, base
    for victim in order:
        drained += trial.allocations[victim].chips
        trial = trial.without(victim)
        if any(True for _ in trial.free_positions(want)):
            return drained
    return None


def point_the_checkpoint_preserving_option_runs_out_first() -> Point:
    """A same-shape move is feasible far less often than a shrink."""
    r = rng()
    pod = Topology.cube(16, 3)
    can_move, can_shrink, trials = 0, 0, 0
    for _ in range(POPULATION):
        fabric = Fabric(pod)
        placed = []
        for i in range(r.randint(2, 6)):
            try:
                fabric.place(Request(job_id=f"j{i}",
                                     chips=r.choice([256, 512, 1024])))
                placed.append(f"j{i}")
            except NoPlacement:
                break
        if not placed:
            continue
        victim = r.choice(placed)
        rect = fabric.allocations[victim]
        coord = tuple(o + r.randrange(e) for o, e in zip(rect.origin, rect.extent))
        trials += 1
        if reembed_same_shape(fabric.cordon(coord), victim).feasible:
            can_move += 1
        if cheapest_shrink(rect, coord).rect is not None:
            can_shrink += 1
    return Point(
        "the-checkpoint-preserving-option-runs-out-first", EMERGENT,
        can_move < can_shrink,
        f"of {trials} failures, a shrink exists in {can_shrink} and a same-shape "
        f"move in only {can_move}; the option that keeps the checkpoint is the one "
        f"that disappears as the pod fills")


def point_the_autonomy_boundary_bites_on_a_full_pod() -> Point:
    """How often recovery has to wait for a person, as occupancy rises."""
    r = rng()
    pod = Topology.cube(16, 3)
    rows = []
    for target in (0.25, 0.50, 0.75, 0.95):
        propose, total = 0, 0
        for _ in range(40):
            fabric = Fabric(pod)
            placed = []
            while fabric.allocated_chips() < target * pod.chips:
                try:
                    fabric.place(Request(job_id=f"j{len(placed)}",
                                         chips=r.choice([256, 512])))
                    placed.append(f"j{len(placed)}")
                except NoPlacement:
                    break
            if not placed:
                continue
            victim = r.choice(placed)
            rect = fabric.allocations[victim]
            coord = tuple(o + r.randrange(e) for o, e in zip(rect.origin, rect.extent))
            result = reconstitution_plan(fabric, victim, coord)
            total += 1
            if result.needs_human:
                propose += 1
        rows.append((target, propose, total))
    rates = [p / max(n, 1) for _, p, n in rows]
    rising = all(rates[i] <= rates[i + 1] for i in range(len(rates) - 1))
    # Monotonicity alone is satisfied by all zeros, which a control plane that
    # never escalates would produce. The boundary must actually bite.
    bites = rates[-1] > rates[0] and rates[-1] > 0.5
    return Point(
        "the-autonomy-boundary-bites-on-a-full-pod", EMERGENT, rising and bites,
        "share of failures needing a human, by occupancy: "
        + ", ".join(f"{int(t * 100)}%: {p}/{n}" for t, p, n in rows)
        + f" --- monotone and reaching {rates[-1] * 100:.0f}% on a nearly full pod, "
          "so the approval queue becomes the outage exactly when the pod is busiest")


def point_a_torus_is_never_worse_than_the_same_mesh() -> Point:
    bad = []
    for k in (3, 4, 5, 6, 8, 16):
        for n in (1, 2, 3):
            torus, mesh = Topology.cube(k, n), Topology.cube(k, n, wrap=False)
            if torus.diameter() > mesh.diameter():
                bad.append(("diameter", k, n))
            if torus.bisection_links() < mesh.bisection_links():
                bad.append(("bisection", k, n))
    return Point(
        "a-torus-is-never-worse-than-the-same-mesh", EMERGENT, not bad,
        f"over 18 (k, n) pairs the torus never has a larger diameter nor a smaller "
        f"bisection than the mesh of the same extents"
        + (f"; exceptions {bad}" if bad else ""))


def point_most_placed_slices_get_no_wraparound_at_all() -> Point:
    r = rng()
    pod = Topology.cube(16, 3)
    counts: Dict[int, int] = {0: 0, 1: 0, 2: 0, 3: 0}
    for _ in range(POPULATION):
        fabric = Fabric(pod)
        for i in range(r.randint(2, 6)):
            try:
                rect = fabric.place(Request(job_id=f"j{i}",
                                            chips=r.choice([128, 256, 512, 1024])))
            except NoPlacement:
                break
            counts[sum(rect.wraps_in(pod))] += 1
    placed = sum(counts.values())
    return Point(
        "most-placed-slices-get-no-wraparound-at-all", EMERGENT,
        placed > 0 and counts[3] == 0,
        f"of {placed} placed slices the wraparound-dimension counts are "
        + ", ".join(f"{d}d: {counts[d]}" for d in sorted(counts))
        + " --- nothing short of the whole pod gets a 3-dimensional torus, so a pod "
          "described as a torus hands most jobs a mesh")


# -- sanity -----------------------------------------------------------------


def point_the_closed_forms_agree_with_brute_force() -> Point:
    bad = []
    for k, n, w in ((4, 2, True), (4, 2, False), (3, 2, True), (3, 3, True),
                    (2, 4, False), (4, 1, True), (6, 1, True), (5, 2, False)):
        pod = Topology.cube(k, n, wrap=w)
        if pod.diameter() != pod.measured_diameter():
            bad.append(("diameter", k, n, w))
        if pod.chips <= 20 and pod.chips % 2 == 0:
            if pod.bisection_links() != pod.measured_bisection():
                bad.append(("bisection", k, n, w))
    return Point(
        "the-closed-forms-agree-with-brute-force", SANITY, not bad,
        "closed-form diameter and bisection match breadth-first search and exact "
        "bipartition enumeration on 8 small pods"
        + (f"; mismatches {bad}" if bad else ""))


def point_every_candidate_shape_is_legal() -> Point:
    pod = Topology.cube(16, 3)
    bad = []
    for chips in (64, 128, 256, 512, 1024, 2048, 4096):
        for shape in candidate_shapes(chips, pod):
            if math.prod(shape) != chips or not SliceRect((0, 0, 0), shape).fits_in(pod):
                bad.append((chips, shape))
    return Point("every-candidate-shape-is-legal", SANITY, not bad,
                 "every shape offered has the requested chip count and fits the pod"
                 + (f"; bad {bad}" if bad else ""))


def point_placements_never_overlap() -> Point:
    r = rng()
    pod = Topology.cube(8, 3)
    bad = 0
    for _ in range(100):
        fabric = Fabric(pod)
        seen = set()
        for i in range(6):
            try:
                rect = fabric.place(Request(job_id=f"j{i}", chips=r.choice([32, 64, 128])))
            except NoPlacement:
                break
            coords = set(rect.coords())
            if coords & seen:
                bad += 1
            seen |= coords
    return Point("placements-never-overlap", SANITY, bad == 0,
                 f"{bad} overlapping placements in 100 random packings")


def point_placeable_never_exceeds_free() -> Point:
    r = rng()
    pod = Topology.cube(8, 3)
    bad = 0
    for _ in range(100):
        fabric = Fabric(pod)
        for i in range(r.randint(1, 5)):
            try:
                fabric.place(Request(job_id=f"j{i}", chips=r.choice([32, 64, 128])))
            except NoPlacement:
                break
        if fabric.largest_placeable() > fabric.free_chips():
            bad += 1
    return Point("placeable-never-exceeds-free", SANITY, bad == 0,
                 f"{bad} of 100 packings claim a placeable job larger than free space")


def point_every_shrink_leaves_a_rectangle_without_the_failure() -> Point:
    bad = []
    for shape in ((6, 6, 6), (4, 9), (2, 3, 5)):
        rect = SliceRect((0,) * len(shape), shape)
        for coord in rect.coords():
            option = cheapest_shrink(rect, coord)
            if option.rect is None:
                continue
            if option.rect.contains(coord) or not set(option.rect.coords()) <= set(rect.coords()):
                bad.append((shape, coord))
    return Point("every-shrink-leaves-a-rectangle-without-the-failure", SANITY, not bad,
                 "over every chip of 3 slices, the cheapest shrink is a rectangle "
                 "inside the original that excludes the failure"
                 + (f"; bad {bad}" if bad else ""))


def point_shrinking_offers_both_faces_of_every_axis() -> Point:
    bad = []
    for shape in ((4, 4, 4), (3, 7), (2, 2, 2, 2)):
        rect = SliceRect((0,) * len(shape), shape)
        centre = tuple(e // 2 for e in shape)
        if len(shrink_options(rect, centre)) != 2 * len(shape):
            bad.append(shape)
    return Point("shrinking-offers-both-faces-of-every-axis", SANITY, not bad,
                 "the option set is exactly two per axis; no interior plane is "
                 "offered, because deleting one would split the slice in two")


def point_repeated_failures_do_not_double_count() -> Point:
    allocs = {"a": SliceRect((0, 0), (8, 8))}
    once = cordon_impact(allocs, [(0, 0)])
    twice = cordon_impact(allocs, [(0, 0), (0, 0)])
    return Point("repeated-failures-do-not-double-count", SANITY,
                 once.losses["a"] == twice.losses["a"],
                 f"a chip failing twice costs {once.losses['a']:,} chips, the same "
                 f"as failing once")


def point_derivations_do_not_mutate_the_fabric() -> Point:
    fabric = Fabric(Topology.cube(8, 3))
    fabric.place(Request(job_id="a", chips=64))
    before = dict(fabric.allocations), set(fabric.unhealthy)
    fabric.without("a")
    fabric.cordon((0, 0, 0))
    reconstitution_plan(fabric, "a", fabric.allocations["a"].origin)
    after = dict(fabric.allocations), set(fabric.unhealthy)
    return Point("derivations-do-not-mutate-the-fabric", SANITY, before == after,
                 "without(), cordon() and the reconstitution planner all leave the "
                 "fabric they were given unchanged")


def point_an_isolated_placement_has_no_violations() -> Point:
    pod = Topology.cube(8, 3)
    fabric, owners = Fabric(pod), {}
    domains = Domains(axis=0)
    placed = 0
    for i in range(8):
        try:
            place_isolated(fabric, Request(job_id=f"j{i}", chips=32,
                                           tenant=f"tenant-{i}"), domains, owners)
            placed += 1
        except NoPlacement:
            break
    found = violations(fabric, domains, owners)
    return Point("an-isolated-placement-has-no-violations", SANITY, not found,
                 f"{placed} tenants placed under a dedicated-rack policy share no "
                 f"rack; {len(found)} violation(s)")


def point_placement_never_wraps_across_the_seam() -> Point:
    pod = Topology.cube(8, 2)
    bad = [r for r in Fabric(pod).positions((4, 4))
           if any(o + e > t for o, e, t in zip(r.origin, r.extent, pod.extents))]
    return Point("placement-never-wraps-across-the-seam", SANITY, not bad,
                 f"{len(bad)} of the offered positions straddle the seam "
                 f"(ASSUMPTIONS A2 says none should)")


def point_an_impossible_request_refuses_rather_than_rounding() -> Point:
    pod = Topology.cube(16, 3)
    return Point("an-impossible-request-refuses-rather-than-rounding", SANITY,
                 candidate_shapes(17, pod) == () and candidate_shapes(4097, pod) == (),
                 "17 chips and 4,097 chips have no rectangle in a 16-cubed pod and "
                 "are refused; nothing is silently rounded up")


REGISTRY: Tuple[Callable[[], Point], ...] = (
    point_diameter_matches_the_published_closed_form,
    point_bisection_matches_the_published_closed_form,
    point_the_worst_single_chip_costs_exactly_half_the_slice,
    point_the_best_case_cordon_is_the_chip_count_over_the_longest_axis,
    point_objective_disagreement_depends_on_the_pod,
    point_free_chips_overstate_what_a_pod_can_admit,
    point_isolation_costs_admitted_chips,
    point_a_full_torus_request_cannot_be_isolated,
    point_the_exact_drain_is_sometimes_cheaper_than_the_greedy_one,
    point_the_checkpoint_preserving_option_runs_out_first,
    point_the_autonomy_boundary_bites_on_a_full_pod,
    point_a_torus_is_never_worse_than_the_same_mesh,
    point_most_placed_slices_get_no_wraparound_at_all,
    point_the_closed_forms_agree_with_brute_force,
    point_every_candidate_shape_is_legal,
    point_placements_never_overlap,
    point_placeable_never_exceeds_free,
    point_every_shrink_leaves_a_rectangle_without_the_failure,
    point_shrinking_offers_both_faces_of_every_axis,
    point_repeated_failures_do_not_double_count,
    point_derivations_do_not_mutate_the_fabric,
    point_an_isolated_placement_has_no_violations,
    point_placement_never_wraps_across_the_seam,
    point_an_impossible_request_refuses_rather_than_rounding,
)


def run_registry() -> List[Point]:
    """Run every point. A point that raises becomes a failing point.

    An exception must not abort the run: one broken check would otherwise make a
    red registry look like a crash and hide every later result.
    """
    results: List[Point] = []
    for check in REGISTRY:
        try:
            results.append(check())
        except Exception as exc:  # noqa: BLE001 - a raising point is a failing point
            results.append(Point(
                check.__name__.removeprefix("point_").replace("_", "-"),
                SANITY, False, f"raised {type(exc).__name__}: {exc}",
            ))
    return results


def main() -> int:
    print("=" * 78)
    print("WHAT THIS REGISTRY DOES NOT CHECK")
    print("=" * 78)
    for i, item in enumerate(DECLINED, 1):
        print(f"{i:2d}. {item}")
    print()

    results = run_registry()
    by_kind: Dict[str, List[Point]] = {CALIBRATED: [], EMERGENT: [], SANITY: []}
    for point in results:
        by_kind[point.kind].append(point)

    for kind in (CALIBRATED, EMERGENT, SANITY):
        points = by_kind[kind]
        print("=" * 78)
        print(f"{kind.upper()}  ({len(points)} points)")
        print("=" * 78)
        for point in points:
            print(f"[{'PASS' if point.passed else 'FAIL'}] {point.name}")
            print(f"       {point.detail}")
            print(f"       ref: {point.reference}")
        print()

    failed = [p for p in results if not p.passed]
    print("=" * 78)
    print(f"{len(results) - len(failed)}/{len(results)} points pass  "
          f"({len(by_kind[CALIBRATED])} calibrated, {len(by_kind[EMERGENT])} emergent, "
          f"{len(by_kind[SANITY])} sanity, {len(DECLINED)} declined)")
    if failed:
        print("failing: " + ", ".join(p.name for p in failed))
    print("=" * 78)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
