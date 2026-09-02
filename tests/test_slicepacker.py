"""Tests for slice-packer-torus.

The topology tests check closed forms against brute-force enumeration on small
pods, because a closed form that is merely self-consistent is worth nothing. The
rest check behaviour that would be easy to get quietly wrong: that a slice
inherits a ring only when it spans the axis, that a cordon never leaves a
non-rectangle, that an exact drain really is cheapest, and that a planner
refuses rather than picking the least-bad illegal action.
"""

from __future__ import annotations

import math

import pytest

from slicepacker import (
    Autonomy,
    AutonomyPolicy,
    Domains,
    Fabric,
    IsolationPolicy,
    Kind,
    NoPlacement,
    Request,
    SliceRect,
    Topology,
    candidate_shapes,
    cheapest_shrink,
    conflicts,
    cordon_cost,
    cordon_impact,
    drain_plan,
    exposure,
    isolation_cost,
    place_isolated,
    reconstitution_plan,
    reembed_same_shape,
    shape_report,
    shrink_options,
    violations,
    worst_position,
)
from slicepacker import cli
from slicepacker.embed import MAX_EXACT_DRAIN_VICTIMS


# -- topology ---------------------------------------------------------------


class TestTopology:
    @pytest.mark.parametrize("k,n,wrap,expected", [
        (4, 2, True, 4), (4, 2, False, 6), (3, 2, True, 2), (5, 2, True, 4),
        (6, 2, False, 10), (4, 3, True, 6), (3, 3, True, 3), (4, 3, False, 9),
    ])
    def test_diameter_matches_the_published_closed_form(self, k, n, wrap, expected):
        assert Topology.cube(k, n, wrap=wrap).diameter() == expected

    @pytest.mark.parametrize("k,n,wrap", [
        (4, 2, True), (4, 2, False), (3, 2, True), (3, 3, True), (2, 4, False),
    ])
    def test_diameter_matches_brute_force(self, k, n, wrap):
        pod = Topology.cube(k, n, wrap=wrap)
        assert pod.diameter() == pod.measured_diameter()

    @pytest.mark.parametrize("k,n,wrap,expected", [
        (4, 2, True, 8), (4, 2, False, 4), (2, 4, False, 8), (4, 1, True, 2),
    ])
    def test_bisection_matches_the_published_closed_form(self, k, n, wrap, expected):
        assert Topology.cube(k, n, wrap=wrap).bisection_links() == expected

    @pytest.mark.parametrize("k,n,wrap", [(4, 2, True), (4, 2, False), (2, 4, False),
                                         (4, 1, True), (6, 1, True)])
    def test_bisection_matches_brute_force(self, k, n, wrap):
        pod = Topology.cube(k, n, wrap=wrap)
        assert pod.bisection_links() == pod.measured_bisection()

    def test_a_ring_of_two_is_not_a_ring(self):
        with pytest.raises(ValueError):
            Topology((2, 4), (True, True))

    def test_chips_is_the_product_of_the_extents(self):
        assert Topology((4, 8, 16), (True,) * 3).chips == 512

    def test_a_torus_is_never_worse_than_the_same_mesh(self):
        for k in (3, 4, 5, 6):
            for n in (1, 2, 3):
                torus = Topology.cube(k, n, wrap=True)
                mesh = Topology.cube(k, n, wrap=False)
                assert torus.diameter() <= mesh.diameter()
                assert torus.bisection_links() >= mesh.bisection_links()


class TestSliceRect:
    def test_a_slice_wraps_only_when_it_spans_the_axis(self):
        pod = Topology.cube(16, 3)
        assert SliceRect((0, 0, 0), (16, 16, 16)).wraps_in(pod) == (True, True, True)
        assert SliceRect((0, 0, 0), (8, 16, 16)).wraps_in(pod) == (False, True, True)
        assert SliceRect((4, 0, 0), (8, 8, 16)).wraps_in(pod) == (False, False, True)

    def test_a_partial_span_is_a_mesh_however_it_is_positioned(self):
        pod = Topology.cube(16, 3)
        for origin in ((0, 0, 0), (1, 0, 0), (8, 0, 0)):
            assert SliceRect(origin, (8, 16, 16)).wraps_in(pod)[0] is False

    def test_overlap_is_symmetric_and_touching_is_not_overlapping(self):
        a = SliceRect((0, 0), (4, 4))
        b = SliceRect((4, 0), (4, 4))
        c = SliceRect((3, 0), (4, 4))
        assert not a.overlaps(b) and not b.overlaps(a)
        assert a.overlaps(c) and c.overlaps(a)

    def test_a_slice_that_does_not_fit_is_rejected_by_fits_in(self):
        pod = Topology.cube(8, 2)
        assert SliceRect((0, 0), (8, 8)).fits_in(pod)
        assert not SliceRect((1, 0), (8, 8)).fits_in(pod)


# -- packing ----------------------------------------------------------------


class TestPacking:
    def test_every_candidate_shape_has_the_right_chip_count_and_fits(self):
        pod = Topology.cube(16, 3)
        for shape in candidate_shapes(1024, pod):
            assert math.prod(shape) == 1024
            assert SliceRect((0, 0, 0), shape).fits_in(pod)

    def test_a_chip_count_with_no_rectangle_returns_nothing(self):
        assert candidate_shapes(17, Topology.cube(16, 3)) == ()

    def test_placement_takes_free_ground_and_release_gives_it_back(self):
        pod = Topology.cube(8, 3)
        fabric = Fabric(pod)
        rect = fabric.place(Request(job_id="a", chips=128))
        assert fabric.allocated_chips() == 128
        assert fabric.free_chips() == pod.chips - 128
        assert fabric.release("a") == rect
        assert fabric.free_chips() == pod.chips

    def test_two_slices_never_share_a_chip(self):
        fabric = Fabric(Topology.cube(8, 3))
        rects = [fabric.place(Request(job_id=f"j{i}", chips=64)) for i in range(6)]
        seen = set()
        for rect in rects:
            coords = set(rect.coords())
            assert not (coords & seen)
            seen |= coords

    def test_a_full_pod_refuses(self):
        fabric = Fabric(Topology.cube(4, 2))
        fabric.place(Request(job_id="a", chips=16))
        with pytest.raises(NoPlacement):
            fabric.place(Request(job_id="b", chips=1))

    def test_placeable_is_never_more_than_free(self):
        fabric = Fabric(Topology.cube(8, 3))
        for i, chips in enumerate((64, 32, 128, 16)):
            fabric.place(Request(job_id=f"j{i}", chips=chips))
        assert fabric.largest_placeable() <= fabric.free_chips()

    def test_fragmentation_is_zero_on_an_empty_pod_and_one_on_a_full_one(self):
        pod = Topology.cube(4, 2)
        assert Fabric(pod).fragmentation() == 0.0
        full = Fabric(pod)
        full.place(Request(job_id="a", chips=16))
        assert full.fragmentation() == 0.0  # no free chips to fragment

    def test_a_hole_can_strand_free_chips(self):
        """Free chips that no single rectangle can reach."""
        pod = Topology.cube(4, 2)
        fabric = Fabric(pod)
        fabric.allocations["mid"] = SliceRect((1, 1), (2, 2))
        assert fabric.free_chips() == 12
        assert fabric.largest_placeable() < 12
        assert fabric.fragmentation() > 0

    def test_placement_never_wraps_across_the_seam(self):
        pod = Topology.cube(8, 2)
        for rect in Fabric(pod).positions((4, 4)):
            assert all(o + e <= t for o, e, t in
                       zip(rect.origin, rect.extent, pod.extents))

    def test_derivations_do_not_mutate_the_receiver(self):
        fabric = Fabric(Topology.cube(8, 3))
        fabric.place(Request(job_id="a", chips=64))
        fabric.without("a")
        fabric.cordon((0, 0, 0))
        assert "a" in fabric.allocations
        assert fabric.unhealthy == set()

    def test_objectives_can_disagree_and_the_disagreement_is_pod_dependent(self):
        """At 16 cubed the three objectives agree; at 64 cubed they do not.

        Worth pinning, because a demonstration built on the small pod would show
        nothing and look like evidence that the objectives never disagree.
        """
        from slicepacker import best_shape
        small, large = Topology.cube(16, 3), Topology.cube(64, 3)
        assert (best_shape(4096, small, objective="diameter")
                == best_shape(4096, small, objective="torus_dims"))
        assert (best_shape(4096, large, objective="diameter")
                != best_shape(4096, large, objective="torus_dims"))
        assert best_shape(4096, large, objective="torus_dims") == (1, 64, 64)


# -- cordon -----------------------------------------------------------------


class TestCordon:
    def test_a_face_failure_costs_one_plane(self):
        rect = SliceRect((0, 0, 0), (16, 16, 16))
        assert cordon_cost(rect, (0, 0, 0)) == 256

    def test_a_centre_failure_costs_half_the_slice(self):
        rect = SliceRect((0, 0, 0), (16, 16, 16))
        assert cordon_cost(rect, (8, 8, 8)) == 2048

    @pytest.mark.parametrize("extent", [
        (16, 16, 16), (4, 16, 64), (8, 8, 64), (1, 64, 64), (64, 64), (32, 128),
    ])
    def test_the_worst_single_chip_always_costs_half_the_slice(self, extent):
        """Shape-independent, and therefore not something packing can fix."""
        rect = SliceRect((0,) * len(extent), extent)
        assert exposure(rect)["worst"] == rect.chips // 2

    @pytest.mark.parametrize("extent", [(16, 16, 16), (4, 16, 64), (8, 8, 64)])
    def test_the_best_case_is_the_smallest_plane(self, extent):
        rect = SliceRect((0,) * len(extent), extent)
        assert exposure(rect)["best"] == rect.chips // max(extent)

    def test_the_compact_cube_has_the_worst_best_case(self):
        """Packing for diameter and packing for failure exposure disagree."""
        cube = SliceRect((0, 0, 0), (16, 16, 16))
        slab = SliceRect((0, 0, 0), (1, 64, 64))
        assert cube.chips == slab.chips
        assert exposure(cube)["best"] > exposure(slab)["best"]

    def test_every_shrink_leaves_a_rectangle_inside_the_original(self):
        rect = SliceRect((0, 0, 0), (6, 6, 6))
        for coord in rect.coords():
            option = cheapest_shrink(rect, coord)
            assert option.rect is not None
            assert not option.rect.contains(coord)
            assert set(option.rect.coords()) <= set(rect.coords())

    def test_shrinking_offers_both_faces_of_every_axis(self):
        rect = SliceRect((0, 0, 0), (4, 4, 4))
        assert len(shrink_options(rect, (1, 1, 1))) == 6

    def test_a_failure_outside_the_slice_is_an_error_not_a_no_op(self):
        with pytest.raises(ValueError):
            shrink_options(SliceRect((0, 0), (4, 4)), (9, 9))

    def test_a_single_chip_slice_is_destroyed_by_its_own_failure(self):
        option = cheapest_shrink(SliceRect((0, 0), (1, 1)), (0, 0))
        assert option.rect is None
        assert option.response.value == "destroyed"

    def test_the_worst_chip_is_interior(self):
        rect = SliceRect((0, 0), (8, 8))
        coord, cost = worst_position(rect)
        assert cost == 32
        assert all(0 < c < 7 for c in coord)

    def test_two_failures_in_one_slice_do_not_double_count(self):
        allocs = {"a": SliceRect((0, 0), (8, 8))}
        once = cordon_impact(allocs, [(0, 0)])
        twice = cordon_impact(allocs, [(0, 0), (0, 0)])
        assert once.losses["a"] == twice.losses["a"]

    def test_a_failure_on_free_ground_touches_nothing(self):
        impact = cordon_impact({"a": SliceRect((0, 0), (2, 2))}, [(7, 7)])
        assert impact.losses == {}
        assert impact.unallocated_hits == 1


# -- embed ------------------------------------------------------------------


class TestEmbed:
    def test_a_same_shape_move_restores_from_checkpoint_and_a_shrink_does_not(self):
        fabric = Fabric(Topology.cube(16, 3))
        fabric.place(Request(job_id="a", chips=1024))
        move = reembed_same_shape(fabric, "a")
        assert move.feasible and move.restore_compatible and move.chips_lost == 0
        shrink = cheapest_shrink(fabric.allocations["a"], (0, 0, 0))
        assert shrink.rect.extent != fabric.allocations["a"].extent

    def test_a_move_that_does_not_move_is_not_a_remedy(self):
        fabric = Fabric(Topology.cube(4, 2))
        fabric.place(Request(job_id="a", chips=16))
        assert not reembed_same_shape(fabric, "a").feasible

    def test_the_exact_drain_beats_the_greedy_one(self):
        """Evicting one big tenant when two small ones would do is the bug."""
        pod = Topology.cube(8, 2)
        fabric = Fabric(pod)
        fabric.allocations = {
            "victim": SliceRect((0, 0), (2, 8)),
            "big": SliceRect((2, 0), (4, 8)),
            "small": SliceRect((6, 0), (2, 8)),
        }
        plan = drain_plan(fabric, "victim")
        assert plan.feasible
        assert plan.drain_chips == min(
            fabric.allocations["big"].chips, fabric.allocations["small"].chips)

    def test_a_protected_tenant_is_never_drained(self):
        fabric = Fabric(Topology.cube(8, 2))
        fabric.allocations = {
            "victim": SliceRect((0, 0), (2, 8)),
            "keep": SliceRect((2, 0), (6, 8)),
        }
        plan = drain_plan(fabric, "victim", protected=["keep"])
        assert not plan.feasible

    def test_too_many_residents_is_refused_not_guessed(self):
        fabric = Fabric(Topology((64, 1), (False, False)))
        fabric.allocations = {"victim": SliceRect((0, 0), (1, 1))}
        for i in range(MAX_EXACT_DRAIN_VICTIMS + 1):
            fabric.allocations[f"r{i}"] = SliceRect((i + 1, 0), (1, 1))
        with pytest.raises(ValueError, match="refusing rather than guessing"):
            drain_plan(fabric, "victim")


# -- tenancy ----------------------------------------------------------------


class TestTenant:
    def test_a_full_wrap_request_cannot_be_isolated(self):
        pod = Topology.cube(16, 3)
        request = Request(job_id="a", chips=4096, min_torus_dims=3)
        assert conflicts(request, pod, Domains(axis=0))

    def test_a_partial_slice_can_be_isolated(self):
        pod = Topology.cube(16, 3)
        request = Request(job_id="a", chips=1024, min_torus_dims=2)
        assert conflicts(request, pod, Domains(axis=0)) == ()

    def test_isolation_never_admits_more_than_an_open_pod(self):
        pod = Topology.cube(16, 3)
        demand = [Request(job_id=f"t{i}", chips=c, tenant=f"tenant-{i}")
                  for i, c in enumerate([1024, 512, 512, 256, 256, 256])]
        cost = isolation_cost(pod, demand, Domains(axis=0))
        assert cost.chips_isolated <= cost.chips_open
        assert 0.0 <= cost.fraction_forgone <= 1.0

    def test_isolation_costs_something_when_jobs_are_smaller_than_a_rack(self):
        """Jobs of exactly one rack cost nothing to isolate; smaller ones do.

        The 64-chip case in an 8-cubed pod is deliberately not used here: each
        such job fills one rack exactly, so isolation is free and the test would
        assert nothing.
        """
        pod = Topology.cube(8, 3)
        domains = Domains(axis=0)
        exact = [Request(job_id=f"e{i}", chips=64, tenant=f"tenant-{i}")
                 for i in range(12)]
        assert isolation_cost(pod, exact, domains).chips_forgone == 0
        smaller = [Request(job_id=f"s{i}", chips=32, tenant=f"tenant-{i}")
                   for i in range(12)]
        assert isolation_cost(pod, smaller, domains).chips_forgone > 0

    def test_an_isolated_placement_has_no_violations(self):
        pod = Topology.cube(8, 3)
        fabric, owners = Fabric(pod), {}
        domains = Domains(axis=0)
        for i in range(3):
            place_isolated(fabric, Request(job_id=f"j{i}", chips=64,
                                           tenant=f"tenant-{i}"), domains, owners)
        assert violations(fabric, domains, owners) == ()

    def test_sharing_a_rack_is_a_violation(self):
        pod = Topology.cube(8, 3)
        fabric = Fabric(pod)
        fabric.allocations = {"a": SliceRect((0, 0, 0), (1, 4, 8)),
                              "b": SliceRect((0, 4, 0), (1, 4, 8))}
        owners = {"a": "red", "b": "blue"}
        found = violations(fabric, Domains(axis=0), owners)
        assert len(found) == 1 and found[0].shared == (0,)

    def test_a_gap_policy_pushes_tenants_further_apart(self):
        pod = Topology.cube(8, 3)
        domains = Domains(axis=0)
        strict = IsolationPolicy(domain_gap=2)
        demand = [Request(job_id=f"t{i}", chips=64, tenant=f"tenant-{i}")
                  for i in range(6)]
        loose = isolation_cost(pod, demand, domains)
        tight = isolation_cost(pod, demand, domains, strict)
        assert tight.chips_isolated <= loose.chips_isolated


# -- reconstitution ---------------------------------------------------------


class TestReconstitute:
    def test_an_empty_pod_lets_the_control_plane_act_alone(self):
        fabric = Fabric(Topology.cube(16, 3))
        fabric.place(Request(job_id="a", chips=1024))
        result = reconstitution_plan(fabric, "a", (2, 8, 8))
        assert result.verdict == "ACT"
        assert result.best.autonomy is Autonomy.L1
        assert not result.needs_human

    def test_a_full_pod_forces_a_human(self):
        fabric = Fabric(Topology.cube(16, 3))
        for job, chips in (("a", 2048), ("b", 1024), ("c", 1024)):
            fabric.place(Request(job_id=job, chips=chips))
        result = reconstitution_plan(fabric, "a", (4, 8, 8))
        assert result.verdict == "PROPOSE"
        assert result.cost_of_waiting is None

    def test_no_autonomous_action_is_not_reported_as_a_free_wait(self):
        fabric = Fabric(Topology.cube(16, 3))
        for job, chips in (("a", 2048), ("b", 2048)):
            fabric.place(Request(job_id=job, chips=chips))
        result = reconstitution_plan(fabric, "a", (4, 8, 8))
        assert result.cost_of_waiting is None
        assert "waits on a person" in result.explain()

    def test_the_planner_never_mutates_the_fabric(self):
        fabric = Fabric(Topology.cube(16, 3))
        fabric.place(Request(job_id="a", chips=1024))
        before = dict(fabric.allocations), set(fabric.unhealthy)
        reconstitution_plan(fabric, "a", (2, 8, 8))
        assert (fabric.allocations, fabric.unhealthy) == before

    def test_a_failure_outside_the_named_job_is_an_error(self):
        fabric = Fabric(Topology.cube(8, 3))
        fabric.place(Request(job_id="a", chips=64))
        with pytest.raises(ValueError):
            reconstitution_plan(fabric, "a", (7, 7, 7))

    def test_eviction_can_be_switched_off_entirely(self):
        fabric = Fabric(Topology.cube(16, 3))
        for job, chips in (("a", 2048), ("b", 2048)):
            fabric.place(Request(job_id=job, chips=chips))
        policy = AutonomyPolicy(allow_eviction=False)
        result = reconstitution_plan(fabric, "a", (4, 8, 8), policy=policy)
        assert all(c.kind is not Kind.DRAIN for c in result.candidates)

    def test_allowing_a_reshard_widens_what_the_control_plane_may_do(self):
        fabric = Fabric(Topology.cube(16, 3))
        for job, chips in (("a", 2048), ("b", 2048)):
            fabric.place(Request(job_id=job, chips=chips))
        strict = reconstitution_plan(fabric, "a", (0, 0, 0))
        loose = reconstitution_plan(
            fabric, "a", (0, 0, 0),
            policy=AutonomyPolicy(allow_reshard=True, max_self_loss_fraction=1.0))
        assert strict.best.autonomy is Autonomy.L0
        assert loose.best.autonomy is Autonomy.L1


# -- command line -----------------------------------------------------------


class TestCLI:
    def test_the_example_runs_clean(self):
        assert cli.main(["example"]) == cli.OK

    def test_shapes_reports_disagreement_on_a_large_pod(self, capsys):
        assert cli.main(["shapes", "4096", "-k", "64", "-n", "3"]) == cli.OK
        assert "DISAGREE" in capsys.readouterr().out

    def test_an_impossible_chip_count_is_refused_not_crashed(self):
        assert cli.main(["shapes", "17", "-k", "16", "-n", "3"]) == cli.REFUSED

    def test_cordon_needs_something_to_work_on(self):
        assert cli.main(["cordon"]) == cli.UNREADABLE

    def test_a_missing_file_is_unreadable(self):
        assert cli.main(["pack", "/nonexistent/scenario.json"]) == cli.UNREADABLE

    def test_cordon_on_a_shape_reports_the_spread(self, capsys):
        assert cli.main(["cordon", "--shape", "8,8,8"]) == cli.OK
        assert "spread" in capsys.readouterr().out


# -- composition ------------------------------------------------------------


class TestComposition:
    def test_pack_fail_reconstitute_release_leaves_the_pod_whole(self):
        pod = Topology.cube(8, 3)
        fabric = Fabric(pod)
        for i, chips in enumerate((64, 64, 128)):
            fabric.place(Request(job_id=f"j{i}", chips=chips))
        result = reconstitution_plan(fabric, "j0", fabric.allocations["j0"].origin)
        assert result.best is not None
        for job in list(fabric.allocations):
            fabric.release(job)
        assert fabric.free_chips() == pod.chips

    def test_a_cordoned_chip_stays_out_of_every_later_placement(self):
        pod = Topology.cube(4, 2)
        fabric = Fabric(pod).cordon((2, 2))
        for rect in fabric.free_positions((2, 2)):
            assert (2, 2) not in set(rect.coords())

    def test_shrink_then_pack_recovers_the_freed_ground(self):
        pod = Topology.cube(8, 3)
        fabric = Fabric(pod)
        fabric.place(Request(job_id="a", chips=256))
        option = cheapest_shrink(fabric.allocations["a"], fabric.allocations["a"].origin)
        fabric.allocations["a"] = option.rect
        assert fabric.free_chips() == pod.chips - option.rect.chips
