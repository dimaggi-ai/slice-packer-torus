"""Break the machinery on purpose and check the registry notices.

A registry that stays green when you delete the thing it is supposed to be
checking is decoration. Each test here removes real machinery --- not a constant
nudged by a percent, but a rule deleted or inverted --- and asserts the *exact*
set of registry points that turns red.

Every red set below was measured, not predicted. Predicting them was tried
first and was wrong nine times out of seventeen, which is itself the argument
for writing the tests this way: an asserted set that came out of a run tells you
which point is load-bearing, while a guessed one tells you what somebody hoped.

:func:`test_unmutated_control` runs first and asserts the registry is green with
nothing mutated, so no red set below can be an artefact of a registry that was
already failing.

The last two tests are the odd ones. They change something real and assert the
registry does **not** notice, because it genuinely cannot: nothing in this
repository is anchored to a measurement of a machine. Printing a blind spot is
worth more than pretending it is covered, and each names the declined item it
corresponds to.
"""

from __future__ import annotations

import itertools
import math
import sys
from typing import Set

import slicepacker.cordon as cordon_mod
import slicepacker.embed as embed_mod
import slicepacker.packing as packing_mod
import slicepacker.reconstitute as reconstitute_mod
import slicepacker.tenant as tenant_mod
import slicepacker.torus as torus_mod
import validate_packing as registry


def red_set() -> Set[str]:
    """Names of the registry points that fail right now."""
    return {p.name for p in registry.run_registry() if not p.passed}


def patch_everywhere(monkeypatch, name: str, replacement) -> None:
    """Replace ``name`` in its own module and in every module that imported it.

    ``from slicepacker.cordon import cheapest_shrink`` binds a second reference.
    Patching only the defining module leaves the registry calling the original,
    and the mutation test then passes for the wrong reason.
    """
    patched = 0
    for module in list(sys.modules.values()):
        if module is None or not getattr(module, "__name__", "").startswith(
            ("slicepacker", "validate_packing")
        ):
            continue
        if hasattr(module, name):
            monkeypatch.setattr(module, name, replacement, raising=True)
            patched += 1
    assert patched, f"nothing to patch for {name!r}; the mutation would be a no-op"


def test_unmutated_control():
    """Green before anything is broken, or every red set below means nothing."""
    assert red_set() == set()


# -- topology ---------------------------------------------------------------


def test_ignore_wraparound_in_the_diameter(monkeypatch):
    """Treat every pod as a mesh and the published torus figures must object.

    The cordon point reddens too, and that is not noise: the best-case cordon
    identity is stated over the longest axis of a slice, and a diameter that has
    forgotten wraparound changes which shape the packer calls best.
    """
    monkeypatch.setattr(
        torus_mod.Topology, "diameter",
        lambda self: sum(e - 1 for e in self.extents))
    assert red_set() == {
        "diameter-matches-the-published-closed-form",
        "the-closed-forms-agree-with-brute-force",
        "the-best-case-cordon-is-the-chip-count-over-the-longest-axis",
    }


def test_ignore_wraparound_in_the_bisection(monkeypatch):
    """Halve the bisection into the mesh figure. Two points hold the line."""
    monkeypatch.setattr(
        torus_mod.Topology, "bisection_links",
        lambda self: math.prod(self.extents) // max(self.extents))
    assert red_set() == {
        "bisection-matches-the-published-closed-form",
        "the-closed-forms-agree-with-brute-force",
    }


def test_hand_a_ring_to_a_slice_that_only_spans_half_the_axis(monkeypatch):
    """Loosen the spanning rule --- the central claim of the whole model.

    An earlier version of this mutation handed a ring to *every* slice, which
    reddened twelve points by making ``Topology`` construction fail on extents
    below three. That proved nothing about the spanning rule, only that the
    model rejects a two-node ring. Half the axis is the smallest loosening that
    still builds legal topologies, and exactly one point catches it.
    """
    monkeypatch.setattr(
        torus_mod.SliceRect, "wraps_in",
        lambda self, pod: tuple(w and e * 2 >= t for e, t, w
                                in zip(self.extent, pod.extents, pod.wrap)))
    assert red_set() == {"most-placed-slices-get-no-wraparound-at-all"}


# -- packing ----------------------------------------------------------------


def test_let_slices_overlap(monkeypatch):
    """Stop checking occupancy. Overlap is not a packing bug in isolation ---
    it silently makes the pod look roomier than it is, so the reconstitution
    points fall over with it."""
    monkeypatch.setattr(packing_mod.Fabric, "is_free",
                        lambda self, rect: rect.fits_in(self.pod))
    assert red_set() == {
        "placements-never-overlap",
        "the-autonomy-boundary-bites-on-a-full-pod",
        "the-checkpoint-preserving-option-runs-out-first",
        "the-exact-drain-is-sometimes-cheaper-than-the-greedy-one",
    }


def test_report_free_chips_as_capacity(monkeypatch):
    """The headline mistake this repository exists to name."""
    monkeypatch.setattr(packing_mod.Fabric, "largest_placeable",
                        lambda self, *, min_torus_dims=0: self.free_chips())
    assert red_set() == {"free-chips-overstate-what-a-pod-can-admit"}


def test_append_one_shape_that_does_not_fit(monkeypatch):
    """Offer a shape longer than the pod alongside the legal ones.

    This one reddens fifteen of the twenty-four points, and the exact set is
    deliberately not asserted: an illegal candidate shape poisons every
    downstream measurement, so the set says only that the mutation is
    catastrophic, not which point is doing the work. The two points named below
    are the ones that catch it *on purpose*.
    """
    original = packing_mod.candidate_shapes
    patch_everywhere(
        monkeypatch, "candidate_shapes",
        lambda chips, pod: tuple(original(chips, pod))
        + ((chips,) + (1,) * (pod.ndim - 1),))
    reds = red_set()
    assert "every-candidate-shape-is-legal" in reds
    assert "an-impossible-request-refuses-rather-than-rounding" in reds
    assert len(reds) > 10, "an illegal shape should be catastrophic, not subtle"


def test_allow_placement_across_the_seam(monkeypatch):
    """Let origins run to the far edge so slices spill round the wrap."""
    def wrapping_positions(self, shape):
        ranges = [range(0, t) for t in self.pod.extents]
        return (torus_mod.SliceRect(origin, shape)
                for origin in itertools.product(*ranges))

    monkeypatch.setattr(packing_mod.Fabric, "positions", wrapping_positions)
    assert red_set() == {"placement-never-wraps-across-the-seam"}


# -- cordon -----------------------------------------------------------------


def test_always_shrink_the_first_axis(monkeypatch):
    """Remove the choice of face and both exposure identities break."""
    def dumb(rect, failed):
        options = cordon_mod.shrink_options(rect, failed)
        survivors = [o for o in options if o.survives and o.axis == 0]
        return survivors[0] if survivors else options[0]

    patch_everywhere(monkeypatch, "cheapest_shrink", dumb)
    assert red_set() == {
        "the-worst-single-chip-costs-exactly-half-the-slice",
        "the-best-case-cordon-is-the-chip-count-over-the-longest-axis",
    }


def test_delete_the_interior_split_guard(monkeypatch):
    """Offer an interior plane deletion, which leaves two slices and not one.

    The widest catch in the file, six points, and every one of them is entitled
    to object: the returned rectangle still contains the failed chip, so the
    shape check, both exposure identities, the double-counting guard and the
    no-mutation check all see something wrong.
    """
    def split(rect, failed):
        kept = torus_mod.SliceRect(rect.origin,
                                   (rect.extent[0] - 1,) + rect.extent[1:])
        return cordon_mod.ShrinkOption(0, "interior", kept,
                                       rect.chips - kept.chips,
                                       cordon_mod.Response.SHRINK)

    patch_everywhere(monkeypatch, "cheapest_shrink", split)
    assert red_set() == {
        "every-shrink-leaves-a-rectangle-without-the-failure",
        "repeated-failures-do-not-double-count",
        "derivations-do-not-mutate-the-fabric",
        "the-worst-single-chip-costs-exactly-half-the-slice",
        "the-best-case-cordon-is-the-chip-count-over-the-longest-axis",
        "the-checkpoint-preserving-option-runs-out-first",
    }


def test_charge_every_failure_against_the_original_slice(monkeypatch):
    """Delete the guard that a second failure lands on the *shrunken* slice.

    The first attempt at this mutation duplicated the caller's failure list
    instead, which tested the arithmetic of the test harness rather than the
    model, and reddened nothing. This one removes the model's own guard.
    """
    def double_counting_impact(allocations, failed):
        survivors, losses, unallocated = {}, {}, 0
        for coord in failed:
            hit = False
            for job_id, rect in allocations.items():
                if not rect.contains(coord):
                    continue
                hit = True
                option = cordon_mod.cheapest_shrink(rect, coord)
                survivors[job_id] = option.rect
                after = option.rect.chips if option.rect else 0
                losses[job_id] = losses.get(job_id, 0) + (rect.chips - after)
            if not hit:
                unallocated += 1
        return cordon_mod.CordonImpact(tuple(failed), survivors, losses,
                                       unallocated)

    patch_everywhere(monkeypatch, "cordon_impact", double_counting_impact)
    assert red_set() == {"repeated-failures-do-not-double-count"}


# -- embed and reconstitution ------------------------------------------------


def test_drain_greedily_instead_of_exactly(monkeypatch):
    """Evict the largest neighbour first --- the plausible wrong planner."""
    def greedy(fabric, job_id, *, shape=None, protected=()):
        before = fabric.allocations[job_id]
        want = shape if shape is not None else before.extent
        base = fabric.without(job_id)
        order = sorted((j for j in base.allocations if j not in set(protected)),
                       key=lambda j: -base.allocations[j].chips)
        trial, victims, drained = base, [], 0
        for victim in order:
            victims.append(victim)
            drained += trial.allocations[victim].chips
            trial = trial.without(victim)
            for rect in trial.free_positions(want):
                return embed_mod._remap(job_id, before, rect,
                                        victims=victims, drain_chips=drained)
        return embed_mod._remap(job_id, before, None)

    patch_everywhere(monkeypatch, "drain_plan", greedy)
    assert red_set() == {"the-exact-drain-is-sometimes-cheaper-than-the-greedy-one"}


def test_pretend_a_move_is_always_available(monkeypatch):
    """Claim the checkpoint-preserving option never runs out.

    Free capacity that is not really there feeds straight into the autonomy
    boundary: a control plane that always believes it can move never asks a
    person, so the escalation point reddens alongside the two it was aimed at.
    """
    def always(fabric, job_id):
        before = fabric.allocations[job_id]
        return embed_mod._remap(job_id, before, before)

    patch_everywhere(monkeypatch, "reembed_same_shape", always)
    assert red_set() == {
        "the-checkpoint-preserving-option-runs-out-first",
        "the-exact-drain-is-sometimes-cheaper-than-the-greedy-one",
        "the-autonomy-boundary-bites-on-a-full-pod",
    }


def test_let_the_control_plane_do_anything(monkeypatch):
    """Grant L1 unconditionally and the autonomy boundary must object.

    This mutation is why the autonomy point was rewritten. As first written the
    point checked only that escalation rose with occupancy, and a control plane
    that never escalates is monotone at zero, so this stayed green. The point
    now requires the boundary to actually bite on a nearly full pod.
    """
    monkeypatch.setattr(reconstitute_mod.Reconstitution, "needs_human",
                        property(lambda self: False))
    assert red_set() == {"the-autonomy-boundary-bites-on-a-full-pod"}


# -- tenancy ----------------------------------------------------------------


def test_collapse_every_rack_into_one_domain(monkeypatch):
    """Make the whole pod a single blast domain, so isolation costs nothing.

    The second mutation that found a hollow point. The isolation point once
    asked only that isolation forgo something, which a policy admitting one
    tenant and refusing the rest satisfies handsomely. It now also requires the
    isolated pod to still admit two workable tenants.
    """
    monkeypatch.setattr(tenant_mod.Domains, "of_rect",
                        lambda self, rect: frozenset({0}))
    assert red_set() == {"isolation-costs-admitted-chips"}


def test_stop_detecting_the_torus_isolation_contradiction(monkeypatch):
    """Accept a request that wants a full ring *and* a private blast domain."""
    patch_everywhere(monkeypatch, "conflicts", lambda request, pod, domains: ())
    assert red_set() == {"a-full-torus-request-cannot-be-isolated"}


def test_stop_checking_isolation_at_placement_time(monkeypatch):
    """Place isolated tenants anywhere free and audit them afterwards."""
    def unchecked(fabric, shape, tenant, domains, owners, policy=None):
        return fabric.free_positions(shape)

    patch_everywhere(monkeypatch, "isolated_positions", unchecked)
    assert red_set() == {
        "an-isolated-placement-has-no-violations",
        "isolation-costs-admitted-chips",
    }


# -- declared blind spots ----------------------------------------------------


def test_the_registry_cannot_see_the_placement_order(monkeypatch):
    """Scan candidate positions backwards and nothing objects.

    Every packing figure in this repository comes out of one first-fit scan in
    one fixed order. Reversing that order changes which slice lands where, and
    the registry is green either way, because no point compares this packer
    against a better one. That is declined item 10, and this test is the proof
    rather than the promise.
    """
    original = packing_mod.Fabric.positions

    def reversed_positions(self, shape):
        return reversed(list(original(self, shape)))

    monkeypatch.setattr(packing_mod.Fabric, "positions", reversed_positions)
    assert red_set() == set(), (
        "the registry cannot tell a first-fit scan from its mirror image, "
        "which is exactly the blind spot declined item 10 names"
    )


def test_the_registry_cannot_see_a_wrong_rack_width():
    """Nothing here knows how wide a real rack is.

    Every isolation figure this repository prints moves when the blast domain is
    redefined, and the registry stays green either way, because no point pins
    the domain width to anything outside the model. That is declined item 11.

    A width of eight is used rather than two or four because at this pod size
    and demand those narrower definitions happen to admit the same tenants ---
    the figures only move once the domain is wide enough to change the packing,
    and a blind-spot test has to show the figures actually moving.
    """
    from slicepacker.packing import Request
    from slicepacker.tenant import Domains, isolation_cost
    from slicepacker.torus import Topology

    pod = Topology.cube(16, 3)
    demand = [Request(job_id=f"t{i}", chips=256, tenant=f"tenant-{i}")
              for i in range(10)]
    narrow = isolation_cost(pod, demand, Domains(axis=0, width=1))
    wide = isolation_cost(pod, demand, Domains(axis=0, width=8))
    assert narrow.chips_isolated != wide.chips_isolated, (
        "if these agreed the blind spot would not exist and this test should go")
    assert red_set() == set(), (
        "the registry is green under both definitions of a rack, which is "
        "exactly the blind spot declined item 11 names"
    )
