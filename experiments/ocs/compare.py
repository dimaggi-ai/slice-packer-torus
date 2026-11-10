#!/usr/bin/env python3
"""Static torus against OCS cubes, on matched pods, arrivals, failures and seeds.

Both pods hold 4,096 chips: the static pod is the 16-ary 3-cube the README's
findings use, and the OCS pod is 64 cubes of 4x4x4 in one switch domain. Every
trial draws one arrival sequence from a seed derived from (workload, occupancy,
trial) and feeds the *same* sequence to both pods, so a difference between the
columns is a difference between the fabrics and not between the draws.

Four comparisons, each including the cases where cubes do not help:

1. free chips against the largest placeable job, by occupancy, for three
   workloads: cube-aligned jobs (the README's own mix), a mix with sub-cube
   jobs, and job sizes that are not whole cubes;
2. what one chip failure costs, by location, with and without a spare cube, and
   how often the checkpoint-preserving recovery exists as the pod fills;
3. diameter and ring inheritance of the slices actually placed;
4. what an OCS port limit does to the largest job and to the gap.

Two static baselines (assurance finding A1, 2026-11-09): ``static`` is the
repository's model, which never places or re-forms a slice across the seam of
a ring (ASSUMPTIONS A2); ``static, seam-crossing`` may (:mod:`slicepacker.seam`).
Fill loops stop at the first refusal, so a target occupancy is not the
occupancy reached: every row reports the chips actually admitted and their
share of the pod (finding A5).

Usage: ``PYTHONPATH=src python experiments/ocs/compare.py [--json PATH] [--quick]``.
Exits 1 if a headline stops holding. Synthetic throughout: no vendor figure is
an input.
"""

from __future__ import annotations

import json
import random
import sys
import time
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, "src")

from slicepacker.cordon import cheapest_shrink  # noqa: E402
from slicepacker.embed import reembed_same_shape  # noqa: E402
from slicepacker.ocs import OCSConfig, OCSPod  # noqa: E402
from slicepacker.packing import Fabric, NoPlacement, Request, candidate_shapes  # noqa: E402
from slicepacker.seam import SeamFabric, cheapest_shrink_across_seam  # noqa: E402
from slicepacker.torus import SliceRect, Topology  # noqa: E402

SEED = 20261109
OCCUPANCIES = (0.10, 0.25, 0.40, 0.55, 0.70, 0.85)
WORKLOADS: Dict[str, List[int]] = {
    # the README finding-2 mix: every size is a whole number of 64-chip cubes
    "cube-aligned": [128, 256, 512, 1024],
    # the same, plus jobs smaller than a cube (GKE sub-slice sizes 16 and 32)
    "with-sub-cube": [16, 32, 128, 256, 512, 1024],
    # sizes the static torus can place and whole cubes cannot hold
    "off-cube": [96, 160, 320, 640],
}
STATIC = Topology.cube(16, 3)


def sequence(workload: str, target: float, trial: int, n: int = 400) -> List[int]:
    r = random.Random(f"{SEED}:{workload}:{target:.2f}:{trial}")
    return [r.choice(WORKLOADS[workload]) for _ in range(n)]


def fill_static(seq: List[int], target: float,
                fabric=Fabric) -> Tuple[Fabric, int, List[str]]:
    fab, refused, placed = fabric(STATIC), 0, []
    for i, chips in enumerate(seq):
        if fab.allocated_chips() >= target * STATIC.chips:
            break
        if not candidate_shapes(chips, STATIC):
            refused += 1
            continue
        try:
            fab.place(Request(job_id=f"j{i}", chips=chips))
            placed.append(f"j{i}")
        except NoPlacement:
            break
    return fab, refused, placed


def fill_ocs(seq: List[int], target: float, pod: OCSPod) -> Tuple[OCSPod, int, List[str]]:
    refused, placed = 0, []
    for i, chips in enumerate(seq):
        if pod.allocated_chips() >= target * pod.chips:
            break
        if not pod.shape_feasible(chips):
            refused += 1
            continue
        try:
            pod.place(f"j{i}", chips)
            placed.append(f"j{i}")
        except NoPlacement:
            break
    return pod, refused, placed


def ocs_pod(cap: Optional[int] = 4, ports: int = 128, **kw) -> OCSPod:
    return OCSPod(64, OCSConfig(max_cubes_per_axis=cap, ocs_ports=ports), **kw)


# -- 1. free vs placeable -----------------------------------------------------


def gap_table(workload: str, trials: int, modes) -> Dict[str, List[dict]]:
    out: Dict[str, List[dict]] = {name: [] for name, _ in modes}
    for target in OCCUPANCIES:
        acc = {name: dict(free=0.0, placeable=0.0, admitted=0.0, refused=0, gapped=0)
               for name, _ in modes}
        for t in range(trials):
            seq = sequence(workload, target, t)
            for name, make in modes:
                if make is None or make == "seam":
                    fab, refused, _ = fill_static(
                        seq, target, Fabric if make is None else SeamFabric)
                    free, place, adm = (fab.free_chips(), fab.largest_placeable(),
                                        fab.allocated_chips())
                else:
                    pod, refused, _ = fill_ocs(seq, target, make())
                    free, place, adm = (pod.free_chips(), pod.largest_placeable(),
                                        pod.allocated_chips())
                a = acc[name]
                a["free"] += free
                a["placeable"] += place
                a["admitted"] += adm
                a["refused"] += refused
                a["gapped"] += int(place < free)
        for name, _ in modes:
            a = acc[name]
            free, place = a["free"] / trials, a["placeable"] / trials
            out[name].append(dict(
                occupancy=target, free=round(free, 1), placeable=round(place, 1),
                overstated=round(1 - place / free, 4) if free else 0.0,
                admitted=round(a["admitted"] / trials, 1),
                admitted_share=round(a["admitted"] / trials / STATIC.chips, 4),
                refused=a["refused"], gapped=a["gapped"], trials=trials))
    return out


def print_gap(workload: str, table: Dict[str, List[dict]]) -> None:
    print(f"\n[{workload}] sizes {WORKLOADS[workload]}")
    names = list(table)
    print(f"  {'target':>7}" + "".join(f"{n:>24}" for n in names))
    print(f"  {'':>7}" + "".join(f"{'reached  overstated':>24}" for _ in names))
    for i, target in enumerate(OCCUPANCIES):
        row = f"  {int(target * 100):>6}%"
        for n in names:
            r = table[n][i]
            row += f"{r['admitted_share'] * 100:>13.1f}%{r['overstated'] * 100:>9.1f}%"
        print(row)
    refused = {n: sum(r["refused"] for r in table[n]) for n in names}
    if any(refused.values()):
        print("  requests refused as unplaceable on an empty pod: "
              + ", ".join(f"{n} {v}" for n, v in refused.items()))


def gap_after_departures(trials: int, modes) -> Dict[str, dict]:
    """Fill cube-aligned jobs to 85%, then release a matched random third.

    Without departures first-fit leaves the free cubes consecutive, which hides
    the difference between stitching any cubes and stitching adjacent ones.
    """
    out = {}
    for name, make in modes:
        free_tot = place_tot = gapped = 0
        for t in range(trials):
            seq = sequence("cube-aligned", 0.85, 4000 + t)
            fab, _, jf = fill_static(seq, 0.85)
            pod, _, jp = fill_ocs(seq, 0.85, ocs_pod(cap=None))
            r = random.Random(f"{SEED}:leave:{t}")
            leaving = [j for j in jf if j in jp and r.random() < 1 / 3]
            if make is None:
                for j in leaving:
                    fab.release(j)
                free, place = fab.free_chips(), fab.largest_placeable()
            elif make == "seam":
                sfab, _, _ = fill_static(seq, 0.85, SeamFabric)
                for j in leaving:
                    if j in sfab.allocations:
                        sfab.release(j)
                free, place = sfab.free_chips(), sfab.largest_placeable()
            else:
                pod2, _, _ = fill_ocs(seq, 0.85, make())
                for j in leaving:
                    if j in pod2.stitched or j in pod2.sub:
                        pod2.release(j)
                free, place = pod2.free_chips(), pod2.largest_placeable()
            free_tot += free
            place_tot += place
            gapped += place < free
        out[name] = dict(free=round(free_tot / trials, 1),
                         placeable=round(place_tot / trials, 1),
                         overstated=round(1 - place_tot / free_tot, 4) if free_tot else 0.0,
                         gapped=gapped, trials=trials)
    return out


# -- 2. failure cost --------------------------------------------------------


LOCATIONS = [("corner", (0, 0, 0)), ("edge", (0, 0, 8)), ("face", (0, 8, 8)),
             ("interior", (4, 8, 8)), ("centre", (8, 8, 8))]


def failure_by_location() -> List[dict]:
    """A 4,096-chip slice (16x16x16) on each fabric; one chip fails."""
    rows = []
    rect = SliceRect((0, 0, 0), (16, 16, 16))
    for label, coord in LOCATIONS:
        static_lost = cheapest_shrink(rect, coord).chips_lost
        static_seam = cheapest_shrink_across_seam(rect, coord, rect.wraps_in(STATIC))
        # OCS: the same slice, 4x4x4 cubes, plus one spare cube in the domain.
        # A 65th cube needs two more ports on every switch: 128 usable ports
        # serve 64 cubes, so the spare case uses all 136 physical Palomar ports
        # (the 8 the TPU v4 paper keeps for testing and repair). With 128 the
        # spare lands in a second domain and cannot be swapped in.
        with_spare = OCSPod(65, OCSConfig(ocs_ports=136), spares=1,
                            spare_policy="reserve")
        s = with_spare.place("big", 4096)
        cube_pos = tuple(c // 4 for c in coord)
        local = tuple(c % 4 for c in coord)
        cube = s.cube_at(cube_pos)
        rec = with_spare.recover("big", cube, local)
        no_spare = OCSPod(64, OCSConfig())
        s2 = no_spare.place("big", 4096)
        rec2 = no_spare.recover("big", s2.cube_at(cube_pos), local)
        how, lost = rec2.best_without_spare()
        rec3 = no_spare.recover("big", s2.cube_at(cube_pos), local, seam_crossing=True)
        how3, lost3 = rec3.best_without_spare()
        rows.append(dict(location=label, coord=coord, static_lost=static_lost,
                         static_lost_seam=static_seam.chips_lost,
                         static_seam_how=static_seam.kind,
                         no_spare_how_seam=how3, no_spare_lost_seam=lost3,
                         swap_lost=rec.best()[1] if rec.can_swap else None,
                         swap_spare_cubes=1 if rec.can_swap else 0,
                         stranded_on_swap=rec.stranded_on_swap,
                         no_spare_how=how, no_spare_lost=lost,
                         no_spare_cordon=rec2.cordon_chips_lost,
                         no_spare_restitch=rec2.restitch_chips_lost))
    return rows


def recovery_by_occupancy(trials: int) -> List[dict]:
    """Matched failures: is the checkpoint-preserving recovery available?

    Static: a same-shape move (``reembed_same_shape``). OCS, borrow policy: a
    whole free cube to swap in. OCS, reserve policy with 2 spares: the same,
    from the held-back pool --- which also shrinks what the pod admits.
    """
    rows = []
    for target in (0.25, 0.50, 0.75, 0.95):
        st_ok = bor_ok = res_ok = n = 0
        res_admitted = bor_admitted = st_admitted = 0
        for t in range(trials):
            seq = sequence("cube-aligned", target, 1000 + t)
            fab, _, st_jobs = fill_static(seq, target)
            bor, _, bor_jobs = fill_ocs(seq, target, ocs_pod())
            res, _, res_jobs = fill_ocs(seq, target,
                                        OCSPod(64, OCSConfig(), spares=2,
                                               spare_policy="reserve"))
            common = [j for j in st_jobs if j in bor_jobs and j in res_jobs]
            if not common:
                continue
            r = random.Random(f"{SEED}:fail:{target}:{t}")
            victim = r.choice(common)
            frac = r.random()
            n += 1
            st_admitted += fab.allocated_chips()
            bor_admitted += bor.allocated_chips()
            res_admitted += res.allocated_chips()
            rect = fab.allocations[victim]
            idx = int(frac * rect.chips)
            coord = _unravel_in(rect, idx)
            st_ok += reembed_same_shape(fab.cordon(coord), victim).feasible
            for pod, which in ((bor, "b"), (res, "r")):
                s = pod.stitched[victim]
                i = int(frac * s.chips)
                cube = s.cubes[i // 64]
                local = _unravel((i % 64), (4, 4, 4))
                ok = pod.recover(victim, cube, local).can_swap
                if which == "b":
                    bor_ok += ok
                else:
                    res_ok += ok
        rows.append(dict(occupancy=target, failures=n, static_move=st_ok,
                         ocs_borrow_swap=bor_ok, ocs_reserve2_swap=res_ok,
                         static_admitted=round(st_admitted / max(n, 1)),
                         borrow_admitted=round(bor_admitted / max(n, 1)),
                         reserve2_admitted=round(res_admitted / max(n, 1)),
                         static_share=round(st_admitted / max(n, 1) / STATIC.chips, 4),
                         borrow_share=round(bor_admitted / max(n, 1) / STATIC.chips, 4),
                         reserve2_share=round(res_admitted / max(n, 1) / STATIC.chips, 4)))
    return rows


def _unravel(i: int, shape) -> tuple:
    out = []
    for s in reversed(shape):
        out.append(i % s)
        i //= s
    return tuple(reversed(out))


def _unravel_in(rect: SliceRect, i: int) -> tuple:
    return tuple(o + x for o, x in zip(rect.origin, _unravel(i, rect.extent)))


# -- 3. rings and diameter --------------------------------------------------


def rings_and_diameter(trials: int) -> dict:
    out = {}
    for name, cfg in (("static", None), ("ocs", OCSConfig()),
                      ("ocs-rings-not-closed", OCSConfig(close_rings=False))):
        wraps = {0: 0, 1: 0, 2: 0, 3: 0}
        diam: Dict[int, List[int]] = {}
        for t in range(trials):
            seq = sequence("with-sub-cube", 0.85, 2000 + t)
            if cfg is None:
                fab, _, jobs = fill_static(seq, 0.85)
                topos = [(fab.allocations[j].chips, fab.allocations[j].topology(STATIC))
                         for j in jobs]
            else:
                pod, _, jobs = fill_ocs(seq, 0.85, OCSPod(64, cfg))
                topos = [((pod.stitched.get(j) or pod.sub[j]).chips,
                          (pod.stitched.get(j) or pod.sub[j]).topology()) for j in jobs]
            for chips, topo in topos:
                wraps[sum(topo.wrap)] += 1
                diam.setdefault(chips, []).append(topo.diameter())
        out[name] = dict(
            wrap_dims=wraps,
            mean_diameter={c: round(sum(v) / len(v), 2) for c, v in sorted(diam.items())})
    return out


# -- 4. port limits --------------------------------------------------------


def port_limits(trials: int) -> List[dict]:
    rows = []
    for ports in (128, 64, 32):
        for cap in (4, None):
            pod = ocs_pod(cap=cap, ports=ports)
            empty_largest = pod.largest_placeable()
            gaps = []
            for target in (0.40, 0.70):
                tot_free = tot_place = 0
                for t in range(trials):
                    seq = sequence("cube-aligned", target, 3000 + t)
                    p, _, _ = fill_ocs(seq, target, ocs_pod(cap=cap, ports=ports))
                    tot_free += p.free_chips()
                    tot_place += p.largest_placeable()
                gaps.append(round(1 - tot_place / tot_free, 4) if tot_free else 0.0)
            rows.append(dict(ocs_ports=ports, cubes_per_domain=ports // 2,
                             max_cubes_per_axis=cap, largest_on_empty_pod=empty_largest,
                             overstated_at_40=gaps[0], overstated_at_70=gaps[1]))
    return rows


# -- main ----------------------------------------------------------------------


def main(argv: List[str]) -> int:
    quick = "--quick" in argv
    json_path = argv[argv.index("--json") + 1] if "--json" in argv else None
    trials = 12 if quick else 60
    started = time.time()
    print("static 16x16x16 torus vs 64 OCS cubes of 4x4x4 (one domain, 128 ports)")
    print(f"seed {SEED}, {trials} matched arrival sequences per occupancy")
    print("'admitted' = chips placed; 'overstated' = 1 - placeable/free, averaged")

    modes = [("static", None), ("static, seam-crossing", "seam"),
             ("ocs cap 4/axis", lambda: ocs_pod(cap=4)),
             ("ocs any shape", lambda: ocs_pod(cap=None))]
    gaps = {w: gap_table(w, trials, modes) for w in WORKLOADS}
    for w, table in gaps.items():
        print_gap(w, table)

    churn = gap_after_departures(trials, modes)
    print("\n[cube-aligned, filled to 85% then a matched third released]")
    for n, r in churn.items():
        print(f"  {n:<22} free {r['free']:>7,.0f}  placeable {r['placeable']:>7,.0f}"
              f"  overstated {r['overstated'] * 100:5.1f}%  gap in {r['gapped']}/{r['trials']}")

    print("\none chip fails in a 4,096-chip 16x16x16 slice: chips lost")
    print(f"  {'':<9}{'no seam-crossing':>34}{'seam-crossing':>30}")
    print(f"  {'where':<9}{'static':>8}{'ocs, no spare':>26}{'static':>10}{'ocs, no spare':>20}"
          f"{'ocs+spare':>11}")
    fail = failure_by_location()
    for r in fail:
        swap = "-" if r["swap_lost"] is None else f"{r['swap_lost']:,}"
        print(f"  {r['location']:<9}{r['static_lost']:>8,}"
              f"{r['no_spare_lost']:>14,} ({r['no_spare_how']:<8})"
              f"{r['static_lost_seam']:>12,}{r['no_spare_lost_seam']:>10,} ({r['no_spare_how_seam']:<8})"
              f"{swap:>9}")
    print("  ocs+spare runs on a 65th cube and 136 rather than 128 ports per switch, and")
    print("  consumes 1 cube (64 chips) of pod capacity per failure; "
          f"{fail[0]['stranded_on_swap']} healthy chips idle until repair")

    rec_trials = 10 if quick else 40
    print("\ncheckpoint-preserving recovery exists (matched failures)")
    rec = recovery_by_occupancy(rec_trials)
    print(f"  {'target':>7}{'static move':>13}{'ocs swap':>10}{'ocs 2 spares':>14}"
          f"{'reached s / b / r':>26}")
    for r in rec:
        print(f"  {int(r['occupancy'] * 100):>6}%{r['static_move']:>8}/{r['failures']:<4}"
              f"{r['ocs_borrow_swap']:>5}/{r['failures']:<4}{r['ocs_reserve2_swap']:>8}/"
              f"{r['failures']:<4}  {r['static_share'] * 100:>6.1f}% / "
              f"{r['borrow_share'] * 100:.1f}% / {r['reserve2_share'] * 100:.1f}%")

    ring_trials = 10 if quick else 30
    rings = rings_and_diameter(ring_trials)
    print("\nwraparound dimensions of placed slices (with-sub-cube mix, 85%)")
    for name, r in rings.items():
        print(f"  {name:<22}" + "  ".join(f"{d}d: {n}" for d, n in r["wrap_dims"].items()))
    print("  mean diameter by job size (chips: static / ocs)")
    for chips in sorted(rings["static"]["mean_diameter"]):
        s = rings["static"]["mean_diameter"][chips]
        o = rings["ocs"]["mean_diameter"].get(chips, "-")
        print(f"    {chips:>5}: {s} / {o}")

    print("\nOCS port limit: domain = ports/2 cubes; stitching never crosses a domain")
    ports = port_limits(10 if quick else 30)
    print(f"  {'ports':>6}{'cubes/dom':>10}{'cap':>6}{'largest, empty':>16}"
          f"{'overst. 40%':>13}{'overst. 70%':>13}")
    for r in ports:
        print(f"  {r['ocs_ports']:>6}{r['cubes_per_domain']:>10}"
              f"{str(r['max_cubes_per_axis']):>6}{r['largest_on_empty_pod']:>16,}"
              f"{r['overstated_at_40'] * 100:>12.1f}%{r['overstated_at_70'] * 100:>12.1f}%")

    # -- headlines -------------------------------------------------------------
    aligned = gaps["cube-aligned"]
    checks = {
        "static overstates capacity on cube-aligned jobs":
            max(r["overstated"] for r in aligned["static"]) >= 0.05,
        "seam-crossing static still overstates capacity on cube-aligned jobs":
            max(r["overstated"] for r in aligned["static, seam-crossing"]) >= 0.05,
        "OCS with any cube shape removes the gap on cube-aligned jobs":
            all(r["overstated"] == 0 for r in aligned["ocs any shape"]),
        "after departures, any-shape OCS still has no gap; static does":
            churn["ocs any shape"]["gapped"] == 0 and churn["static"]["gapped"] > 0,
        "sub-cube jobs bring a gap back under OCS":
            any(r["overstated"] > 0 for r in gaps["with-sub-cube"]["ocs any shape"]),
        "off-cube sizes are refused by OCS and placed by static":
            sum(r["refused"] for r in gaps["off-cube"]["ocs any shape"]) > 0
            and sum(r["refused"] for r in gaps["off-cube"]["static"]) == 0,
        "with a spare cube (a 65th cube, 136 ports), failure cost is zero everywhere":
            all(r["swap_lost"] == 0 for r in fail),
        "no seam-crossing only: without a spare, OCS caps the worst case below static":
            max(r["no_spare_lost"] for r in fail) < max(r["static_lost"] for r in fail),
        "seam-crossing on both: without a spare, OCS and static lose the same":
            all(r["no_spare_lost_seam"] == r["static_lost_seam"] for r in fail),
        "OCS slices get closed rings; static slices mostly do not":
            rings["ocs"]["wrap_dims"][3] > 0 and rings["static"]["wrap_dims"][3] == 0,
        "no closing circuit, no ring":
            rings["ocs-rings-not-closed"]["wrap_dims"][3] == 0,
        "a port limit below 2x cubes makes the whole-pod job unplaceable":
            all(r["largest_on_empty_pod"] < 4096 for r in ports if r["ocs_ports"] < 128),
        "a full pod leaves no cube to borrow":
            rec[-1]["ocs_borrow_swap"] < rec[0]["ocs_borrow_swap"],
    }
    print()
    for k, v in checks.items():
        print(f"  [{'ok' if v else 'NO'}] {k}")
    holds = all(checks.values())
    print(f"\n{'headline holds' if holds else 'HEADLINE NO LONGER HOLDS'}"
          f"  ({time.time() - started:.0f}s)")

    if json_path:
        with open(json_path, "w") as fh:
            json.dump(dict(seed=SEED, trials=trials, workloads=WORKLOADS, gap=gaps,
                           failure_by_location=fail, recovery_by_occupancy=rec,
                           rings_and_diameter=rings, port_limits=ports,
                           gap_after_departures=churn,
                           checks=checks, holds=holds),
                      fh, indent=1, default=str)
    return 0 if holds else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
