"""The OCS-cube mode: behaviour, then mutations of its machinery.

The first half tests :mod:`slicepacker.ocs` directly. The second half follows
``test_mutations.py``: each test deletes or inverts one rule of the new model
and asserts the exact set of points in ``validation/validate_ocs.py`` that turns
red. Every red set was measured, not predicted. The static registry and its
mutation suite are not touched by anything here.
"""

from __future__ import annotations

import pytest

import slicepacker.ocs as ocs_mod
import validate_ocs as registry
from slicepacker.ocs import (
    OCSConfig,
    OCSPod,
    StitchedSlice,
    measured_diameter,
    stitch_circuits,
    stitched_graph,
)
from slicepacker.packing import NoPlacement


# -- behaviour ----------------------------------------------------------------


def test_default_config_matches_the_tpu_v4_arithmetic():
    cfg = OCSConfig()
    assert cfg.cube_chips == 64
    assert cfg.ocs_count == 48
    assert cfg.cubes_per_domain == 64


def test_config_rejects_nonsense():
    with pytest.raises(ValueError):
        OCSConfig(ocs_ports=7)
    with pytest.raises(ValueError):
        OCSConfig(geometry=(4, 0, 4))
    with pytest.raises(ValueError):
        OCSConfig(max_cubes_per_axis=0)
    with pytest.raises(ValueError):
        OCSConfig(subcube_shapes=((2, 2),))


def test_pod_rejects_bad_spare_settings():
    with pytest.raises(ValueError):
        OCSPod(4, spares=4, spare_policy="reserve")
    with pytest.raises(ValueError):
        OCSPod(4, spares=1, spare_policy="borrow")
    with pytest.raises(ValueError):
        OCSPod(4, spare_policy="hope")


def test_stitching_needs_a_count_not_a_region():
    pod = OCSPod(8)
    pod.place("a", 64)
    pod.place("b", 64)
    pod.release("a")  # cube 0 free, cube 1 held: no contiguous run of two
    s = pod.place("c", 128)
    assert set(s.cubes) == {0, 2}


def test_the_ring_is_a_circuit():
    open_ = StitchedSlice("x", (2, 1, 1), (0, 1),
                          stitch_circuits((2, 1, 1), (0, 1), close_rings=False),
                          (4, 4, 4))
    closed = StitchedSlice("x", (2, 1, 1), (0, 1),
                           stitch_circuits((2, 1, 1), (0, 1), close_rings=True),
                           (4, 4, 4))
    assert open_.wraps() == (False, False, False)
    assert closed.wraps() == (True, True, True)
    # remove one closing bundle and that axis is a mesh again
    partial = StitchedSlice("x", (2, 1, 1), (0, 1),
                            closed.circuits - {(0, 1, 0)}, (4, 4, 4))
    assert partial.wraps() == (False, True, True)
    assert measured_diameter(stitched_graph(partial)) == partial.topology().diameter()


def test_graph_and_closed_form_agree_on_mixed_rings():
    cubes = (0, 1, 2, 3, 4, 5)
    closed = stitch_circuits((3, 2, 1), cubes, close_rings=True)
    closing = closed - stitch_circuits((3, 2, 1), cubes, close_rings=False)
    # open axis 1 on every line: drop all of its closing circuits
    circuits = closed - {c for c in closing if c[0] == 1}
    s = StitchedSlice("x", (3, 2, 1), cubes, circuits, (4, 4, 4))
    assert s.wraps() == (True, False, True)
    assert measured_diameter(stitched_graph(s)) == s.topology().diameter()


def test_an_axis_closed_on_only_some_lines_is_not_a_ring():
    # Measured while building: open ONE of the three axis-1 lines and the graph
    # still loops on the other two (diameter 12), but the slice cannot rely on
    # a ring, so wraps() says False and the closed form (15) is an upper bound.
    cubes = (0, 1, 2, 3, 4, 5)
    closed = stitch_circuits((3, 2, 1), cubes, close_rings=True)
    closing = closed - stitch_circuits((3, 2, 1), cubes, close_rings=False)
    one_line = sorted(c for c in closing if c[0] == 1)[:1]
    s = StitchedSlice("x", (3, 2, 1), cubes, closed - set(one_line), (4, 4, 4))
    assert s.wraps() == (True, False, True)
    assert measured_diameter(stitched_graph(s)) < s.topology().diameter()


def test_sub_slices_share_a_cube_and_block_stitching():
    pod = OCSPod(2)
    a = pod.place("a", 32)
    b = pod.place("b", 32)
    assert a.cube == b.cube
    assert not pod.is_whole_free(a.cube)
    with pytest.raises(NoPlacement):
        pod.place("c", 128)
    assert pod.largest_placeable() == 64


def test_sub_slices_are_meshes_unless_rings_are_asked_for():
    plain = OCSPod(1).place("a", 32)
    assert plain.wraps() == (False, False, False)
    ringed = OCSPod(1, OCSConfig(subcube_rings=True)).place("a", 32)
    assert sum(ringed.wraps()) == 2  # 2x4x4: the two full-span axes


def test_off_cube_sizes_are_refused_not_rounded():
    pod = OCSPod(8)
    with pytest.raises(NoPlacement):
        pod.place("a", 96)
    with pytest.raises(NoPlacement):
        pod.place("b", 24)  # no allowed sub-cube shape
    assert pod.allocated_chips() == 0


def test_shape_cap_refuses_counts_with_no_shape():
    pod = OCSPod(64)
    assert not pod.shape_feasible(5 * 64)
    assert OCSPod(64, OCSConfig(max_cubes_per_axis=None)).shape_feasible(5 * 64)


def test_domains_split_the_pod():
    pod = OCSPod(64, OCSConfig(ocs_ports=64))
    assert len(pod.domains()) == 2
    with pytest.raises(NoPlacement):
        pod.place("a", 33 * 64)
    s = pod.place("b", 32 * 64)
    assert len({pod.domain(c) for c in s.cubes}) == 1


def test_swap_recovery_costs_nothing_but_a_cube():
    pod = OCSPod(64, spares=1, spare_policy="reserve")
    s = pod.place("a", 1024)
    rec = pod.recover("a", s.cubes[3], (2, 2, 2))
    assert rec.can_swap and rec.best() == ("swap", 0)
    assert rec.stranded_on_swap == 63
    pod.apply_swap("a", s.cubes[3], (2, 2, 2))
    assert pod.spare_pool == []
    assert pod.recover("a", pod.stitched["a"].cubes[0], (0, 0, 0)).can_swap is False


def test_without_a_spare_the_cheaper_of_cordon_and_restitch_wins():
    pod = OCSPod(64)
    s = pod.place("all", 4096)
    corner = pod.recover("all", s.cube_at((0, 0, 0)), (0, 0, 0))
    centre = pod.recover("all", s.cube_at((2, 2, 2)), (0, 0, 0))
    assert not corner.can_swap
    assert corner.best_without_spare() == ("cordon", 256)
    assert corner.cordon_wraps.count(False) == 1  # the shrunk axis loses its ring
    assert centre.best_without_spare() == ("restitch", 1024)


def test_recover_rejects_a_cube_outside_the_slice():
    pod = OCSPod(8)
    pod.place("a", 128)
    with pytest.raises(ValueError):
        pod.recover("a", 7, (0, 0, 0))


def test_fail_validates_coordinates():
    pod = OCSPod(2)
    with pytest.raises(ValueError):
        pod.fail(5, (0, 0, 0))
    with pytest.raises(ValueError):
        pod.fail(0, (4, 0, 0))


def test_release_unknown_job_is_an_error():
    with pytest.raises(KeyError):
        OCSPod(2).release("nobody")


def test_ocs_registry_is_green():
    assert {p.name for p in registry.run_registry() if not p.passed} == set()


# -- mutations ------------------------------------------------------------------


def red_set():
    return {p.name for p in registry.run_registry() if not p.passed}


def test_assume_every_stitched_slice_wraps(monkeypatch):
    """Report a ring wherever the extent allows one, circuit or not."""
    monkeypatch.setattr(ocs_mod.StitchedSlice, "wraps",
                        lambda self: tuple(e >= 3 for e in self.extents))
    assert red_set() == MEASURED["assume_wraps"]


def test_never_close_the_ring(monkeypatch):
    """Stitch the neighbours and forget the closing bundle."""
    original = ocs_mod.stitch_circuits
    monkeypatch.setattr(ocs_mod, "stitch_circuits",
                        lambda shape, cubes, *, close_rings: original(
                            shape, cubes, close_rings=False))
    monkeypatch.setattr(registry, "stitch_circuits", ocs_mod.stitch_circuits)
    assert red_set() == MEASURED["never_close"]


def test_ignore_the_port_limit(monkeypatch):
    """One domain whatever the switch radix."""
    monkeypatch.setattr(ocs_mod.OCSPod, "domain", lambda self, cube: 0)
    assert red_set() == MEASURED["no_domains"]


def test_no_cube_swap(monkeypatch):
    monkeypatch.setattr(ocs_mod.OCSPod, "swap_target", lambda self, job, cube: None)
    assert red_set() == MEASURED["no_swap"]


def test_no_restitch(monkeypatch):
    monkeypatch.setattr(ocs_mod.Recovery, "best_without_spare",
                        lambda self: ("cordon", self.cordon_chips_lost))
    assert red_set() == MEASURED["no_restitch"]


def test_stitching_needs_adjacent_cubes(monkeypatch):
    """Delete the OCS: only the longest run of consecutive free cubes counts."""
    original = ocs_mod.OCSPod.whole_free

    def contiguous(self, members):
        free = set(original(self, members))
        best, run = [], []
        for c in members:
            if c in free:
                run.append(c)
                if len(run) > len(best):
                    best = list(run)
            else:
                run = []
        return best

    monkeypatch.setattr(ocs_mod.OCSPod, "whole_free", contiguous)
    assert red_set() == MEASURED["adjacent_only"]


def test_ignore_the_shape_cap(monkeypatch):
    original = ocs_mod.OCSPod.cube_shapes

    def uncapped(self, m, limit):
        cfg = self.config
        self.config = OCSConfig(cfg.geometry, cfg.ocs_ports, None, cfg.close_rings,
                                cfg.subcube_shapes, cfg.subcube_rings)
        try:
            return original(self, m, limit)
        finally:
            self.config = cfg

    monkeypatch.setattr(ocs_mod.OCSPod, "cube_shapes", uncapped)
    assert red_set() == MEASURED["no_cap"]


def test_stitch_cubes_that_hold_sub_slices(monkeypatch):
    """Forget that a shared cube is not free for stitching."""
    def loose(self, cube, *, include_spares=False):
        if not include_spares and cube in self.spare_pool:
            return False
        return self.owner(cube) is None and not self.unhealthy.get(cube)

    monkeypatch.setattr(ocs_mod.OCSPod, "is_whole_free", loose)
    assert red_set() == MEASURED["stitch_shared"]


def test_sub_slices_never_share_a_cube(monkeypatch):
    """A blind spot, asserted: one cube per small job is a real change in
    utilisation, and no point measures sub-cube utilisation."""
    monkeypatch.setattr(
        ocs_mod.OCSPod, "_subcube_hosts",
        lambda self: [c for c in range(self.n_cubes) if self.is_whole_free(c)][:1])
    assert red_set() == MEASURED["no_sharing"]


#: Every set below came out of a run, not a prediction. One surprise is
#: recorded in validate_ocs.py: the adjacency mutation first measured EMPTY,
#: because first-fit with no departures leaves free cubes consecutive; the gap
#: point now releases a matched third of the jobs before it measures.
MEASURED = {
    "assume_wraps": {"a-stitched-slice-is-the-textbook-torus-or-mesh"},
    "never_close": {
        "a-stitched-slice-is-the-textbook-torus-or-mesh",
        "stitched-slices-get-the-rings-static-slices-do-not",
        "the-default-pod-has-the-tpu-v4-switch-arithmetic",
    },
    "no_domains": {
        "a-port-limit-caps-the-largest-job",
        "no-port-carries-two-circuits",
        "stitching-never-crosses-a-domain",
    },
    "no_swap": {
        "a-spare-cube-makes-failure-cost-location-independent",
        "a-swap-keeps-the-shape-and-drops-the-failed-cube",
        "spares-are-paid-for-either-way",
    },
    "no_restitch": {"without-a-spare-cubes-halve-the-worst-case"},
    "adjacent_only": {"cubes-remove-the-gap-for-cube-aligned-jobs"},
    "no_cap": {
        "a-shape-menu-brings-a-gap-back",
        "sizes-that-are-not-whole-cubes-are-refused",
        "without-a-spare-cubes-halve-the-worst-case",
    },
    "stitch_shared": {
        "no-cube-is-held-twice",
        "ocs-accounting-adds-up",
        "sub-cube-jobs-bring-a-gap-back",
    },
    # the blind spot: nothing measures how well small jobs share cubes
    "no_sharing": set(),
}
