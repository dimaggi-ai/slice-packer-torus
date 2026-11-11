#!/usr/bin/env python3
"""The OCS-cube registry: what it declines first, then what it checks.

A separate registry from ``validate_packing.py`` on purpose. The static-torus
registry, its 29 points and the exact red sets its mutation tests assert are
left byte-for-byte as they were; this file adds the points for
:mod:`slicepacker.ocs`, in the same three kinds and with the same rule that a
sanity point cites nothing. ``tests/test_ocs.py`` deletes the new machinery
and asserts which of these points turn red.

Run it: ``PYTHONPATH=src python validation/validate_ocs.py``. Exit status is 1
if any point fails.
"""

from __future__ import annotations

import random
import sys
from typing import Dict, List, Tuple

sys.path.insert(0, "src")
sys.path.insert(0, "validation")

from validate_packing import CALIBRATED, DALLY, EMERGENT, SANITY, Point  # noqa: E402

from slicepacker.cordon import cheapest_shrink  # noqa: E402
from slicepacker.ocs import (  # noqa: E402
    OCSConfig,
    OCSPod,
    StitchedSlice,
    measured_diameter,
    stitch_circuits,
    stitched_graph,
)
from slicepacker.packing import Fabric, NoPlacement, Request, candidate_shapes  # noqa: E402
from slicepacker.seam import cheapest_shrink_across_seam  # noqa: E402
from slicepacker.torus import SliceRect, Topology  # noqa: E402

SEED = 20261109
#: Matched arrival sequences per randomised point; small so the mutation suite
#: can rerun the registry once per mutation.
POPULATION = 16

JOUPPI = ("Jouppi et al., 'TPU v4: An Optically Reconfigurable Supercomputer for "
          "Machine Learning with Hardware Support for Embeddings', ISCA 2023 "
          "(arXiv:2304.01433): 64 blocks of 4x4x4, 48 OCSes, 136x136 Palomar "
          "switches with 128 ports in use")

DECLINED: Tuple[str, ...] = (
    "No measured OCS pod. Every number here is a model output on synthetic "
    "arrivals; nothing has been compared with a real pod, a real OCS or GKE's "
    "slice controller.",
    "Google's 'up to 5x faster start' and 'up to 4.5x faster recovery' for "
    "dynamic slicing are VENDOR CLAIMS. They are cited in docs/ocs-cubes.md and "
    "are not an input to any point. There is no time in this model, so neither "
    "could be checked here.",
    "OCS reconfiguration time, optical insertion loss and the latency of a "
    "switched hop are not modelled: a circuit counts as one hop, exactly like an "
    "electrical link.",
    "OCS failure, fibre failure and link failure are not modelled. Only chips "
    "fail (as in the static model, declined item 3 there).",
    "Twisted tori and any wiring other than 'face position p on axis d goes to "
    "switch (d, p)' are not modelled. That wiring is the TPU v4 paper's; a pod "
    "wired differently has a different port limit.",
    "Hosts, racks, power and cooling are not modelled: a cube is the only "
    "boundary, and a spare cube's location is free to choose.",
    "Whether a sub-cube slice may loop a full-span axis through the OCS is not "
    "documented publicly. It is off by default (subcube_rings) and no point "
    "depends on it.",
    "The allowed super-slice shapes are a parameter (max_cubes_per_axis), not "
    "GKE's published list. The shape menu moves the gap, as the points show.",
    "Placement is first-fit at cube granularity, in one arrival order. The only "
    "departures are one matched release of a third of the jobs in the gap "
    "point; there is no arrival process or job lifetime --- the static model's "
    "declined items on time and first-fit placement apply unchanged.",
    "The spare-cube case runs on more hardware than the static pod: a 65th cube "
    "and all 136 Palomar ports (the 8 the paper keeps for testing and repair). "
    "No static spare is modelled; a static torus has no cube to swap in. Its "
    "zero is a cost moved into hardware, not removed.",
    "The static registry's cordon and placement never cross the seam of a ring "
    "(ASSUMPTIONS A2). The failure points here report both that baseline and a "
    "seam-crossing one (slicepacker.seam); the gap points use the first only, and "
    "experiments/ocs/compare.py measures the second.",
    "Cube geometry is a parameter, but only 4x4x4 is tested. No point, test or "
    "experiment uses another cube size, and the comparison fixes 64 cubes of "
    "4x4x4. The results are not claimed for any other geometry.",
    "A sub-cube slice has no failure path. recover() and apply_swap() refuse a "
    "sub-cube job with ValueError; swap, re-stitch and cordon cover stitched "
    "slices only.",
)


def rng() -> random.Random:
    return random.Random(SEED)


def _seq(tag: str, i: int, sizes: List[int], n: int = 200) -> List[int]:
    r = random.Random(f"{SEED}:{tag}:{i}")
    return [r.choice(sizes) for _ in range(n)]


def _fill(seq: List[int], target: float, pod=None, fabric=None):
    """Same rule for both fabrics: skip what no empty pod could hold, stop at
    the first request that does not fit."""
    placed = []
    for i, chips in enumerate(seq):
        if pod is not None:
            if pod.allocated_chips() >= target * pod.chips:
                break
            if not pod.shape_feasible(chips):
                continue
            try:
                pod.place(f"j{i}", chips)
            except NoPlacement:
                break
        else:
            if fabric.allocated_chips() >= target * fabric.pod.chips:
                break
            if not candidate_shapes(chips, fabric.pod):
                continue
            try:
                fabric.place(Request(job_id=f"j{i}", chips=chips))
            except NoPlacement:
                break
        placed.append(f"j{i}")
    return placed


STATIC = Topology.cube(16, 3)
ALIGNED = [128, 256, 512, 1024]
MIXED = [16, 32, 128, 256, 512, 1024]


# -- calibrated -------------------------------------------------------------


def point_the_default_pod_has_the_tpu_v4_switch_arithmetic() -> Point:
    cfg = OCSConfig()
    pod = OCSPod(64, cfg)
    full = pod.place("whole", 64 * cfg.cube_chips)
    usage = pod.port_usage()
    ok = (cfg.ocs_count == 48 and cfg.cubes_per_domain == 64 and pod.chips == 4096
          and len(pod.domains()) == 1 and len(usage) == 48
          and max(usage.values()) == cfg.ocs_ports)
    return Point(
        "the-default-pod-has-the-tpu-v4-switch-arithmetic", CALIBRATED, ok,
        f"64 cubes of 4x4x4 = {pod.chips:,} chips on {cfg.ocs_count} switches; a "
        f"whole-pod {'x'.join(map(str, full.cube_shape))}-cube slice uses "
        f"{max(usage.values())} of {cfg.ocs_ports} usable ports on every switch",
        JOUPPI)


def point_a_stitched_slice_is_the_textbook_torus_or_mesh() -> Point:
    """Built from circuits, measured by BFS, compared with the closed forms."""
    bad = []
    cases = 0
    for shape in ((1, 1, 1), (2, 1, 1), (3, 1, 1), (2, 2, 1), (3, 2, 1)):
        for close in (True, False):
            cubes = tuple(range(shape[0] * shape[1] * shape[2]))
            s = StitchedSlice("x", shape, cubes,
                              stitch_circuits(shape, cubes, close_rings=close),
                              (4, 4, 4))
            published = sum(e // 2 if close else e - 1 for e in s.extents)
            measured = measured_diameter(stitched_graph(s))
            cases += 1
            if measured != published or s.topology().diameter() != published:
                bad.append((shape, close, measured, published))
    return Point(
        "a-stitched-slice-is-the-textbook-torus-or-mesh", CALIBRATED, not bad,
        f"in {cases} stitched slices built only from OCS circuits, breadth-first "
        "diameter equals the published torus form when the closing circuit is set "
        "and the mesh form when it is not"
        + (f"; mismatches {bad}" if bad else ""),
        DALLY)


# -- emergent ----------------------------------------------------------------


def point_cubes_remove_the_gap_for_cube_aligned_jobs() -> Point:
    """Fill to 85%, then let a matched random third of the jobs leave.

    The departures are load-bearing. Without them first-fit leaves the free
    cubes as one consecutive run, so a pod that could only stitch *adjacent*
    cubes --- one with the OCS deleted --- scored the same, and this point stayed
    green on machinery that was no longer there. Measured, then fixed.
    """
    static_gapped = ocs_gapped = 0
    for i in range(POPULATION):
        seq = _seq("aligned", i, ALIGNED)
        fab = Fabric(STATIC)
        jf = _fill(seq, 0.85, fabric=fab)
        pod = OCSPod(64, OCSConfig(max_cubes_per_axis=None))
        jp = _fill(seq, 0.85, pod=pod)
        r = random.Random(f"{SEED}:leave:{i}")
        for j in [j for j in jf if j in jp and r.random() < 1 / 3]:
            fab.release(j)
            pod.release(j)
        static_gapped += fab.largest_placeable() < fab.free_chips()
        ocs_gapped += pod.largest_placeable() < pod.free_chips()
    return Point(
        "cubes-remove-the-gap-for-cube-aligned-jobs", EMERGENT,
        static_gapped > 0 and ocs_gapped == 0,
        f"same {POPULATION} arrival sequences, filled to 85% and a third released: "
        f"free chips overstate the largest placeable job in {static_gapped} static "
        f"packings and {ocs_gapped} OCS packings (any cube shape allowed)")


def point_a_shape_menu_brings_a_gap_back() -> Point:
    capped = 0
    for i in range(POPULATION):
        pod = OCSPod(64, OCSConfig(max_cubes_per_axis=4))
        _fill(_seq("aligned", i, ALIGNED), 0.55, pod=pod)
        capped += pod.largest_placeable() < pod.free_chips()
    return Point(
        "a-shape-menu-brings-a-gap-back", EMERGENT, capped > 0,
        f"with stitched shapes capped at 4 cubes per axis, {capped} of {POPULATION} "
        "of the same packings overstate: a free-cube count with no legal shape "
        "(47 cubes -> 36) is the cube-granular version of the static gap")


def point_sub_cube_jobs_bring_a_gap_back() -> Point:
    gapped, stranded = 0, []
    for i in range(POPULATION):
        pod = OCSPod(64, OCSConfig(max_cubes_per_axis=None))
        _fill(_seq("mixed", i, MIXED), 0.70, pod=pod)
        free, place = pod.free_chips(), pod.largest_placeable()
        if place < free:
            gapped += 1
            stranded.append(free - place)
    return Point(
        "sub-cube-jobs-bring-a-gap-back", EMERGENT, gapped > 0,
        f"with 16- and 32-chip jobs in the mix, {gapped} of {POPULATION} OCS packings "
        f"strand free chips inside shared cubes (median "
        f"{sorted(stranded)[len(stranded) // 2] if stranded else 0} chips): a cube "
        "with any sub-slice in it cannot be stitched")


def point_sizes_that_are_not_whole_cubes_are_refused() -> Point:
    pod = OCSPod(64, OCSConfig())
    refused = [c for c in (96, 160, 320, 640) if not pod.shape_feasible(c)]
    static_ok = all(candidate_shapes(c, STATIC) for c in (96, 160, 320, 640))
    return Point(
        "sizes-that-are-not-whole-cubes-are-refused", EMERGENT,
        static_ok and len(refused) == 4,
        f"the static torus has a rectangle for 96, 160, 320 and 640 chips; the OCS "
        f"pod (4 cubes per axis) refuses {refused} --- 1.5 and 2.5 cubes are not "
        "cubes, and 5 and 10 cubes have no shape under the cap")


def _location_rows():
    """Per location: static, OCS with a spare, OCS bare --- then the same two
    without a spare when either fabric may cross its seam."""
    rect = SliceRect((0, 0, 0), (16, 16, 16))
    out = []
    for coord in ((0, 0, 0), (0, 0, 8), (0, 8, 8), (4, 8, 8), (8, 8, 8)):
        static = cheapest_shrink(rect, coord).chips_lost
        static_seam = cheapest_shrink_across_seam(rect, coord, rect.wraps_in(STATIC)).chips_lost
        spare = OCSPod(65, OCSConfig(ocs_ports=136), spares=1, spare_policy="reserve")
        s = spare.place("big", 4096)
        pos, local = tuple(c // 4 for c in coord), tuple(c % 4 for c in coord)
        rec = spare.recover("big", s.cube_at(pos), local)
        bare = OCSPod(64, OCSConfig())
        s2 = bare.place("big", 4096)
        rec2 = bare.recover("big", s2.cube_at(pos), local)
        rec3 = bare.recover("big", s2.cube_at(pos), local, seam_crossing=True)
        out.append((static, rec.best()[1] if rec.can_swap else None,
                    rec2.best_without_spare()[1], static_seam,
                    rec3.best_without_spare()[1]))
    return out


def point_a_spare_cube_makes_one_failure_cost_nothing() -> Point:
    """Restated after assurance finding A1. It was 'a spare cube makes failure
    cost location-independent'; a torus that may cross its seam is
    location-independent too (one plane, 256 chips), so that is not the
    difference. The difference is zero against one plane, bought with a 65th
    cube and 8 more ports per switch."""
    rows = _location_rows()
    static = [r[0] for r in rows]
    swap = [r[1] for r in rows]
    seam = [r[3] for r in rows]
    ok = (all(s == 0 for s in swap) and max(static) >= 8 * min(static)
          and len(set(seam)) == 1 and seam[0] > 0)
    return Point(
        "a-spare-cube-makes-one-failure-cost-nothing", EMERGENT, ok,
        f"one chip fails in a 16x16x16 slice at five locations: OCS with one spare "
        f"cube loses {swap}; static loses {static} if it may not cross its seam and "
        f"{seam} if it may --- the spare costs a 65th cube and 136 rather than 128 "
        "ports per switch, and one cube of capacity per failure")


def point_without_a_spare_cubes_only_beat_a_torus_that_cannot_cross_its_seam() -> Point:
    """Restated after assurance finding A1. It was 'without a spare, cubes halve
    the worst case'; that holds only against the no-seam static cordon."""
    rows = _location_rows()
    static = [r[0] for r in rows]
    bare = [r[2] for r in rows]
    static_seam = [r[3] for r in rows]
    bare_seam = [r[4] for r in rows]
    ok = (max(bare) * 2 == max(static) and min(bare) == min(static)
          and bare_seam == static_seam and len(set(static_seam)) == 1)
    return Point(
        "without-a-spare-cubes-only-beat-a-torus-that-cannot-cross-its-seam", EMERGENT, ok,
        f"no spare: OCS loses {bare} against static {static} when neither crosses "
        f"its seam (re-stitching caps the worst case at a quarter of the slice); "
        f"when both may, OCS loses {bare_seam} and static {static_seam} --- no "
        "difference")


def point_stitched_slices_get_the_rings_static_slices_do_not() -> Point:
    static_3d = ocs_3d = ocs_whole = 0
    for i in range(POPULATION):
        seq = _seq("rings", i, ALIGNED)
        fab = Fabric(STATIC)
        for j in _fill(seq, 0.85, fabric=fab):
            static_3d += fab.allocations[j].torus_dims(STATIC) == 3
        pod = OCSPod(64, OCSConfig())
        for j in _fill(seq, 0.85, pod=pod):
            ocs_whole += 1
            ocs_3d += sum(pod.stitched[j].wraps()) == 3
    return Point(
        "stitched-slices-get-the-rings-static-slices-do-not", EMERGENT,
        ocs_whole > 0 and ocs_3d == ocs_whole and static_3d == 0,
        f"same arrivals: {ocs_3d} of {ocs_whole} stitched slices close a ring in all "
        f"three axes, against {static_3d} static slices --- the ring follows the "
        "circuit, so its length is the job's, not the pod's")


def point_a_port_limit_caps_the_largest_job() -> Point:
    largest = {p: OCSPod(64, OCSConfig(ocs_ports=p, max_cubes_per_axis=None))
               .largest_placeable() for p in (128, 64, 32)}
    ok = largest == {128: 4096, 64: 2048, 32: 1024}
    return Point(
        "a-port-limit-caps-the-largest-job", EMERGENT, ok,
        f"empty 64-cube pod, largest job by usable OCS ports: {largest}; a switch "
        "serves ports/2 cubes and stitching never leaves that domain, which the "
        "static torus (4,096 chips) never pays")


def point_spares_are_paid_for_either_way() -> Point:
    borrow_low = borrow_high = reserve_high = 0
    adm_borrow = adm_reserve = 0
    for i in range(POPULATION):
        for target in (0.25, 0.95):
            seq = _seq(f"spare{target}", i, [256, 512, 1024])
            b = OCSPod(64, OCSConfig())
            rr = OCSPod(64, OCSConfig(), spares=2, spare_policy="reserve")
            jb = _fill(seq, target, pod=b)
            jr = _fill(seq, target, pod=rr)
            if not jb or not jr:
                continue
            sb = b.stitched[jb[0]]
            sr = rr.stitched[jr[0]]
            okb = b.recover(jb[0], sb.cubes[0], (0, 0, 0)).can_swap
            okr = rr.recover(jr[0], sr.cubes[0], (0, 0, 0)).can_swap
            if target == 0.25:
                borrow_low += okb
            else:
                borrow_high += okb
                reserve_high += okr
                adm_borrow += b.allocated_chips()
                adm_reserve += rr.allocated_chips()
    ok = borrow_high < borrow_low and reserve_high == POPULATION and adm_reserve < adm_borrow
    return Point(
        "spares-are-paid-for-either-way", EMERGENT, ok,
        f"borrowing a free cube works in {borrow_low}/{POPULATION} failures at 25% and "
        f"{borrow_high}/{POPULATION} at 95%; holding 2 cubes back works in "
        f"{reserve_high}/{POPULATION} at 95% and admits "
        f"{(adm_borrow - adm_reserve) / POPULATION:,.0f} fewer chips per pod")


# -- sanity -----------------------------------------------------------------


def _random_pods(n: int = 20):
    r = rng()
    for _ in range(n):
        pod = OCSPod(r.choice([16, 64, 96]),
                     OCSConfig(ocs_ports=r.choice([32, 64, 128]),
                               max_cubes_per_axis=r.choice([2, 4, None])))
        for i in range(r.randint(4, 30)):
            try:
                pod.place(f"j{i}", r.choice([16, 32, 64, 128, 256, 512]))
            except NoPlacement:
                pass
        # one failure, swapped out where a free cube allows it
        if pod.stitched:
            s = pod.stitched[sorted(pod.stitched)[0]]
            try:
                pod.apply_swap(s.job_id, s.cubes[0], (0, 0, 0))
            except NoPlacement:
                pass
        yield pod


def point_no_cube_is_held_twice() -> Point:
    bad = 0
    for pod in _random_pods():
        seen: Dict[int, str] = {}
        for s in pod.stitched.values():
            for c in s.cubes:
                if c in seen or c in pod.partial_cubes():
                    bad += 1
                seen[c] = s.job_id
    return Point("no-cube-is-held-twice", SANITY, bad == 0,
                 f"{bad} cubes in two slices, or stitched while shared, in 20 random pods")


def point_no_port_carries_two_circuits() -> Point:
    bad = []
    for pod in _random_pods():
        try:
            usage = pod.port_usage()
            if usage and max(usage.values()) > pod.config.ocs_ports:
                bad.append("over radix")
        except ValueError as exc:
            bad.append(str(exc))
    return Point("no-port-carries-two-circuits", SANITY, not bad,
                 "every OCS port carries at most one circuit and no switch exceeds "
                 "its usable ports in 20 random pods" + (f"; {bad[:3]}" if bad else ""))


def point_stitching_never_crosses_a_domain() -> Point:
    bad = 0
    pods = 0
    for pod in _random_pods():
        if len(pod.domains()) < 2:
            continue
        pods += 1
        for s in pod.stitched.values():
            if len({pod.domain(c) for c in s.cubes}) != 1:
                bad += 1
    return Point("stitching-never-crosses-a-domain", SANITY, bad == 0 and pods > 0,
                 f"{bad} cross-domain slices in {pods} multi-domain pods")


def point_a_swap_keeps_the_shape_and_drops_the_failed_cube() -> Point:
    pod = OCSPod(64, OCSConfig(), spares=2, spare_policy="reserve")
    s = pod.place("a", 1024)
    failed = s.cubes[5]
    new = pod.apply_swap("a", failed, (1, 2, 3))
    ok = (new.cube_shape == s.cube_shape and failed not in new.cubes
          and len(pod.spare_pool) == 1 and new.wraps() == s.wraps()
          and not pod.is_whole_free(failed, include_spares=True))
    return Point("a-swap-keeps-the-shape-and-drops-the-failed-cube", SANITY, ok,
                 "after a swap the slice has the same cube shape and rings, the failed "
                 "cube is out of it and unusable, and the spare pool is one smaller")


def point_reserved_spares_are_per_domain() -> Point:
    """Assurance finding A3: a swap never leaves its domain, so every domain
    needs its own spares. Two domains (64 ports), two spares each."""
    pod = OCSPod(64, OCSConfig(ocs_ports=64), spares=2, spare_policy="reserve")
    held = [sum(c in pod.spare_pool for c in d) for d in pod.domains()]
    swaps = []
    for d, members in enumerate(pod.domains()):
        trial = pod.copy()
        free = [c for c in members if trial.is_whole_free(c)][:8]
        trial.stitched[f"d{d}"] = StitchedSlice(
            f"d{d}", (2, 2, 2), tuple(free),
            stitch_circuits((2, 2, 2), free, close_rings=True), trial.config.geometry)
        swaps.append(trial.recover(f"d{d}", free[0], (0, 0, 0)).can_swap)
    ok = held == [2, 2] and all(swaps)
    return Point("reserved-spares-are-per-domain", SANITY, ok,
                 f"64 cubes, 64 ports, 2 spares: spares held per domain {held}; a "
                 f"failure in each domain finds a swap {swaps}")


def point_a_copy_keeps_used_spares_used() -> Point:
    """Assurance finding A4: an emptied pool is a state, not a default."""
    pod = OCSPod(64, OCSConfig(), spares=1, spare_policy="reserve")
    s = pod.place("a", 1024)
    pod.apply_swap("a", s.cubes[0], (0, 0, 0))
    twin = pod.copy()
    ok = pod.spare_pool == [] and twin.spare_pool == [] and not twin.recover(
        "a", twin.stitched["a"].cubes[1], (0, 0, 0)).can_swap
    return Point("a-copy-keeps-used-spares-used", SANITY, ok,
                 f"after the only spare is used, the pod holds {pod.spare_pool} and "
                 f"its copy holds {twin.spare_pool}")


def point_ocs_accounting_adds_up() -> Point:
    bad = 0
    for pod in _random_pods():
        stitched = sum(len(s.cubes) for s in pod.stitched.values()) * pod.config.cube_chips
        sub = sum(s.chips for s in pod.sub.values())
        held = {c for s in pod.stitched.values() for c in s.cubes}
        sick = sum(len(v) for c, v in pod.unhealthy.items() if c not in held)
        if pod.free_chips() + stitched + sub + sick != pod.chips:
            bad += 1
        if pod.largest_placeable() > pod.free_chips():
            bad += 1
    return Point("ocs-accounting-adds-up", SANITY, bad == 0,
                 f"free + allocated + unhealthy = pod, and placeable <= free: {bad} "
                 "violations in 20 random pods, each with one chip failure")


REGISTRY = (
    point_the_default_pod_has_the_tpu_v4_switch_arithmetic,
    point_a_stitched_slice_is_the_textbook_torus_or_mesh,
    point_cubes_remove_the_gap_for_cube_aligned_jobs,
    point_a_shape_menu_brings_a_gap_back,
    point_sub_cube_jobs_bring_a_gap_back,
    point_sizes_that_are_not_whole_cubes_are_refused,
    point_a_spare_cube_makes_one_failure_cost_nothing,
    point_without_a_spare_cubes_only_beat_a_torus_that_cannot_cross_its_seam,
    point_stitched_slices_get_the_rings_static_slices_do_not,
    point_a_port_limit_caps_the_largest_job,
    point_spares_are_paid_for_either_way,
    point_no_cube_is_held_twice,
    point_no_port_carries_two_circuits,
    point_stitching_never_crosses_a_domain,
    point_a_swap_keeps_the_shape_and_drops_the_failed_cube,
    point_reserved_spares_are_per_domain,
    point_a_copy_keeps_used_spares_used,
    point_ocs_accounting_adds_up,
)


def run_registry() -> List[Point]:
    results: List[Point] = []
    for check in REGISTRY:
        try:
            results.append(check())
        except Exception as exc:  # noqa: BLE001 - a raising point is a failing point
            results.append(Point(
                check.__name__.removeprefix("point_").replace("_", "-"),
                SANITY, False, f"raised {type(exc).__name__}: {exc}"))
    return results


def main() -> int:
    print("=" * 78)
    print("WHAT THE OCS REGISTRY DOES NOT CHECK")
    print("=" * 78)
    for i, item in enumerate(DECLINED, 1):
        print(f"{i:2d}. {item}")
    print()
    results = run_registry()
    by_kind: Dict[str, List[Point]] = {CALIBRATED: [], EMERGENT: [], SANITY: []}
    for p in results:
        by_kind[p.kind].append(p)
    for kind in (CALIBRATED, EMERGENT, SANITY):
        print("=" * 78)
        print(f"{kind.upper()}  ({len(by_kind[kind])} points)")
        print("=" * 78)
        for p in by_kind[kind]:
            print(f"[{'PASS' if p.passed else 'FAIL'}] {p.name}")
            print(f"       {p.detail}")
            print(f"       ref: {p.reference}")
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
