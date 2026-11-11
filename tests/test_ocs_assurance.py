"""Regressions for the assurance findings on the OCS mode (2026-11-09, A1-A8).

Each test here was written and run *before* its fix, and failed; the failing
run is kept with the build evidence. A1 is the static baseline: a torus that
may re-form a slab across its seam. A3 and A4 are the reserve-policy spare
pool. A8 is the OCS port check.
"""

from __future__ import annotations

import pytest

from slicepacker.cordon import cheapest_shrink
from slicepacker.ocs import OCSConfig, OCSPod, SubSlice, StitchedSlice, stitch_circuits
from slicepacker.packing import Fabric, NoPlacement, Request
from slicepacker.torus import SliceRect, Topology


# -- A3: reserved spares are held per domain ------------------------------------


def test_reserve_holds_spares_in_every_domain():
    """64 ports serve 32 cubes, so 64 cubes make two domains. Two spares each."""
    pod = OCSPod(64, OCSConfig(ocs_ports=64), spares=2, spare_policy="reserve")
    assert len(pod.domains()) == 2
    for members in pod.domains():
        assert sum(c in pod.spare_pool for c in members) == 2
    # a slice in the first domain finds a spare in its own domain
    s = pod.place("a", 64 * 8)
    assert {pod.domain(c) for c in s.cubes} == {0}
    assert pod.recover("a", s.cubes[0], (0, 0, 0)).can_swap


def test_reserve_feasibility_matches_what_is_held_back():
    pod = OCSPod(64, OCSConfig(ocs_ports=64, max_cubes_per_axis=None),
                 spares=2, spare_policy="reserve")
    # 30 of each domain's 32 cubes are placeable, in either domain
    assert pod.shape_feasible(30 * 64)
    assert not pod.shape_feasible(31 * 64)
    pod.place("a", 30 * 64)
    pod.place("b", 30 * 64)


def test_reserve_rejects_more_spares_than_a_domain_holds():
    with pytest.raises(ValueError):
        OCSPod(64, OCSConfig(ocs_ports=64), spares=32, spare_policy="reserve")


# -- A4: copy() keeps a used-up spare pool used up ------------------------------


def test_copy_after_the_spares_are_used_has_no_spares():
    pod = OCSPod(64, spares=1, spare_policy="reserve")
    s = pod.place("a", 1024)
    pod.apply_swap("a", s.cubes[0], (0, 0, 0))
    assert pod.spare_pool == []
    twin = pod.copy()
    assert twin.spare_pool == []
    assert twin.recover("a", twin.stitched["a"].cubes[1], (0, 0, 0)).can_swap is False


def test_copy_keeps_a_partly_used_pool():
    pod = OCSPod(64, spares=2, spare_policy="reserve")
    s = pod.place("a", 1024)
    pod.apply_swap("a", s.cubes[0], (0, 0, 0))
    assert pod.copy().spare_pool == pod.spare_pool == [63]


# -- A8: the port check looks at the face positions actually used --------------


def _looped_sub(pod: OCSPod, job: str, cube: int, origin, extent) -> SubSlice:
    rect = SliceRect(origin, extent)
    circuits = frozenset((axis, cube, cube) for axis, (e, g)
                         in enumerate(zip(extent, pod.config.geometry)) if e == g)
    s = SubSlice(job, cube, rect, circuits, pod.config.geometry)
    pod.sub[job] = s
    return s


def test_sub_slices_looping_disjoint_face_positions_pass():
    pod = OCSPod(4, OCSConfig(subcube_rings=True))
    _looped_sub(pod, "a", 0, (0, 0, 0), (2, 2, 4))
    _looped_sub(pod, "b", 0, (2, 0, 0), (2, 2, 4))
    pod.port_usage()  # disjoint positions on the axis-2 face: legal


def test_two_loops_on_the_same_face_position_are_caught():
    """Overlapping sub-slices are illegal anyway; the port check must still see
    the shared position rather than waive every self-loop on a shared cube."""
    pod = OCSPod(4, OCSConfig(subcube_rings=True))
    _looped_sub(pod, "a", 0, (0, 0, 0), (2, 2, 4))
    _looped_sub(pod, "b", 0, (1, 0, 0), (2, 2, 4))
    with pytest.raises(ValueError):
        pod.port_usage()


def test_a_stitched_loop_on_a_shared_cube_is_caught():
    """A one-cube stitched slice with closed rings loops its cube on every
    axis, using every face position. A sub-slice looping the same cube collides."""
    pod = OCSPod(4, OCSConfig(subcube_rings=True))
    _looped_sub(pod, "a", 0, (0, 0, 0), (2, 2, 4))
    pod.stitched["b"] = StitchedSlice("b", (1, 1, 1), (0,),
                                      stitch_circuits((1, 1, 1), (0,), close_rings=True),
                                      pod.config.geometry)
    with pytest.raises(ValueError):
        pod.port_usage()


def test_sub_slice_loops_count_only_their_positions():
    pod = OCSPod(4, OCSConfig(subcube_rings=True))
    _looped_sub(pod, "a", 0, (0, 0, 0), (2, 2, 4))
    usage = pod.port_usage()
    # four face positions on axis 2 (2x2 cross-section), two ports each
    assert sum(usage.values()) == 4 * 2
    assert {k[1] for k in usage} == {2}


# -- A1: a torus that may re-form its slab across the seam ---------------------


LOCATIONS = ((0, 0, 0), (0, 0, 8), (0, 8, 8), (4, 8, 8), (8, 8, 8))


def test_seam_crossing_shrink_loses_one_plane_anywhere():
    from slicepacker.seam import cheapest_shrink_across_seam

    rect = SliceRect((0, 0, 0), (16, 16, 16))
    for coord in LOCATIONS:
        best = cheapest_shrink_across_seam(rect, coord, (True, True, True))
        assert best.chips_lost == 256
        assert best.wraps_after.count(False) == 1


def test_seam_crossing_needs_a_ring():
    from slicepacker.seam import cheapest_shrink_across_seam

    rect = SliceRect((0, 0, 0), (16, 16, 16))
    for coord in LOCATIONS:
        best = cheapest_shrink_across_seam(rect, coord, (False, False, False))
        assert best.chips_lost == cheapest_shrink(rect, coord).chips_lost
        assert best.kind == "face"


def test_seam_crossing_prefers_the_face_on_a_tie():
    from slicepacker.seam import cheapest_shrink_across_seam

    best = cheapest_shrink_across_seam(SliceRect((0, 0, 0), (16, 16, 16)),
                                       (0, 0, 0), (True, True, True))
    assert best.kind == "face" and best.chips_lost == 256


def test_ocs_recovery_with_seam_crossing_matches_the_torus():
    pod = OCSPod(64)
    s = pod.place("all", 4096)
    rec = pod.recover("all", s.cube_at((2, 2, 2)), (0, 0, 0), seam_crossing=True)
    assert rec.best_without_spare() == ("cordon", 256)
    assert rec.cordon_wraps.count(False) == 1
    # and the default is unchanged
    assert pod.recover("all", s.cube_at((2, 2, 2)), (0, 0, 0)).best_without_spare() \
        == ("restitch", 1024)


def test_seam_fabric_places_across_the_seam():
    from slicepacker.seam import SeamFabric

    pod = Topology.cube(4, 1)
    fab = SeamFabric(pod)
    fab.place(Request(job_id="a", chips=2))      # chips 0 and 1
    fab.place(Request(job_id="b", chips=1))      # chip 2
    fab.release("a")
    # free: 0, 1 and 3 --- three in a row only across the seam (3, 0, 1)
    assert Fabric(pod, dict(fab.allocations)).largest_placeable() == 2
    assert fab.largest_placeable() == 3
    assert fab.free_chips() == 3
    r = fab.place(Request(job_id="d", chips=3))
    assert r.origin == (3,) and fab.free_chips() == 0


def test_seam_fabric_matches_fabric_when_nothing_wraps():
    from slicepacker.seam import SeamFabric

    mesh = Topology((4, 4), (False, False))
    a, b = Fabric(mesh), SeamFabric(mesh)
    for i, chips in enumerate((4, 2, 6, 1)):
        ra = a.place(Request(job_id=f"j{i}", chips=chips))
        rb = b.place(Request(job_id=f"j{i}", chips=chips))
        assert ra == rb
    assert a.largest_placeable() == b.largest_placeable()
    assert a.free_chips() == b.free_chips()


def _brute_largest(fab) -> int:
    """Every shape, every origin, the slow modular test: the reference."""
    from slicepacker.packing import _shapes_by_volume
    for shape, volume in _shapes_by_volume(tuple(fab.pod.extents)):
        if volume > fab.free_chips():
            continue
        if any(fab.is_free(r) for r in fab.positions(shape)):
            return volume
    return 0


@pytest.mark.parametrize("extents,wrap", [
    ((4, 4, 4), (True, True, True)),
    ((4, 3, 5), (True, False, True)),
    ((5, 4), (False, True)),
    ((6,), (True,)),
])
def test_seam_fabric_bitmasks_match_the_brute_force(extents, wrap):
    import random
    from slicepacker.seam import SeamFabric

    r = random.Random(f"seam:{extents}")
    for trial in range(15):
        fab = SeamFabric(Topology(extents, wrap))
        for i in range(r.randint(1, 12)):
            try:
                fab.place(Request(job_id=f"j{i}", chips=r.choice([1, 2, 3, 4, 6, 8])))
            except Exception:
                pass
        for j in [k for k in fab.allocations if r.random() < 0.3]:
            fab.release(j)
        if r.random() < 0.5:
            fab.unhealthy.add(tuple(r.randrange(e) for e in extents))
        # every placement is legal and disjoint
        cells = [c for rect in fab.allocations.values() for c in
                 (tuple(x % e for x, e in zip(cc, extents)) for cc in rect.coords())]
        assert len(cells) == len(set(cells))
        assert fab.largest_placeable() == _brute_largest(fab)
        # and first-fit agrees with the slow scan
        for shape in ((2,) + (1,) * (len(extents) - 1), (1,) * len(extents)):
            slow = next((rr.origin for rr in fab.positions(shape) if fab.is_free(rr)), None)
            assert fab._first_origin(shape) == slow


# -- CTO review of PR #1 (2026-11-10): reserve spares stay in their domain ------


def test_reserve_swap_takes_the_spare_of_the_failed_cubes_domain():
    """Two domains of 32 cubes, two spares each. Fill domain 0, so the next job
    lands in domain 1, then fail one of its cubes. The swap must take domain
    1's spare (62), not domain 0's (30), which no circuit can reach."""
    pod = OCSPod(64, OCSConfig(ocs_ports=64), spares=2, spare_policy="reserve")
    assert pod.spare_pool == [30, 31, 62, 63]
    for name, chips in (("a", 1024), ("b", 512), ("c", 256), ("d", 128)):
        assert {pod.domain(c) for c in pod.place(name, chips).cubes} == {0}
    victim = pod.place("v", 512)
    assert {pod.domain(c) for c in victim.cubes} == {1}
    failed = victim.cubes[0]
    assert pod.swap_target("v", failed) == 62
    assert pod.recover("v", failed, (0, 0, 0)).swap_cube == 62
    swapped = pod.apply_swap("v", failed, (0, 0, 0))
    assert {pod.domain(c) for c in swapped.cubes} == {1}
    assert pod.spare_pool == [30, 31, 63]
    pod.port_usage()  # raises if any circuit crosses a domain


def test_reserve_swap_is_refused_when_only_another_domain_has_a_spare():
    pod = OCSPod(64, OCSConfig(ocs_ports=64), spares=1, spare_policy="reserve")
    assert pod.spare_pool == [31, 63]
    first = pod.place("a", 512)
    assert {pod.domain(c) for c in first.cubes} == {0}
    pod.apply_swap("a", first.cubes[0], (0, 0, 0))
    assert pod.spare_pool == [63]
    # domain 0 has used its spare; domain 1's spare is out of reach
    rec = pod.recover("a", pod.stitched["a"].cubes[1], (0, 0, 0))
    assert rec.swap_cube is None and not rec.can_swap
    with pytest.raises(NoPlacement):
        pod.apply_swap("a", pod.stitched["a"].cubes[1], (0, 0, 0))


# -- CTO review: the shape cap is clamped to the domain size ---------------------


def test_cube_shapes_never_exceed_the_limit_passed_in():
    """No caller inside the model passes more cubes than ``limit``, so the
    clamp changes nothing there. Called directly, ``limit`` still bounds every
    axis: 4 cubes in a 2-cube limit have (1, 2, 2) and not (1, 1, 4)."""
    pod = OCSPod(64, OCSConfig(max_cubes_per_axis=4))
    shapes = pod.cube_shapes(4, 2)
    assert shapes and all(max(s) <= 2 for s in shapes)
    assert pod.cube_shapes(3, 2) == ()


# -- CTO review: a sub-cube slice has no failure path, and says so ---------------


def test_recover_refuses_a_sub_cube_job_by_name():
    pod = OCSPod(4)
    small = pod.place("small", 32)
    with pytest.raises(ValueError, match="sub-cube slice"):
        pod.recover("small", small.cube, (0, 0, 0))


def test_apply_swap_refuses_a_sub_cube_job_and_changes_nothing():
    pod = OCSPod(4)
    small = pod.place("small", 32)
    with pytest.raises(ValueError, match="sub-cube slice"):
        pod.apply_swap("small", small.cube, (0, 0, 0))
    assert pod.unhealthy == {} and pod.sub["small"] == small


def test_recover_on_an_unknown_job_is_still_a_key_error():
    with pytest.raises(KeyError):
        OCSPod(4).recover("nobody", 0, (0, 0, 0))
