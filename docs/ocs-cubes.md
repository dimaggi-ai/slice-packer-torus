# OCS cubes: what optical stitching removes, and what it does not

Every other model in this repository assumes one static torus. This one models
a pod built from **cubes joined by optical circuit switches (OCS)**, and
compares it with the static torus on matched pods, arrivals, failures and
seeds. Module: `src/slicepacker/ocs.py`. Experiment:
`experiments/ocs/compare.py`. Registry: `validation/validate_ocs.py`. Tests and
mutations: `tests/test_ocs.py` and `tests/test_ocs_assurance.py`. The
seam-crossing static baseline: `src/slicepacker/seam.py`.

It is a model, not a measurement. Nothing here has met a real pod, a real OCS
or a real slice controller.

## Why now

Google announced general availability of GKE *dynamic slicing* on
9 November 2026. The slice controller reconfigures the OCS fabric to stitch
4x4x4 TPU cubes into larger slices (super-slicing) or carve smaller ones out of
a cube (sub-slicing). Google says this gives **up to 5x faster job start and up
to 4.5x faster recovery**. Those two figures are **vendor claims**. They are
quoted here for context only, are **not an input** to anything in this model,
and could not be checked by it: the model has no time.

The static findings this module is aimed at are README findings 1--3: placed
slices almost never get a closed ring, free chips overstate capacity by 8--30%,
and one chip failure costs 6--50% of a slice depending on where it is. The
last rests on the static model's rule that no slice crosses the seam of a ring
(ASSUMPTIONS A2); section 2 reports it without that rule too.

## The model

| Element | Rule | Source or label |
| --- | --- | --- |
| Cube | A fixed electrical mesh, `geometry` chips (default 4x4x4 = 64) | 4x4x4 blocks: Jouppi et al., ISCA 2023; GKE docs. The 64-chip figure follows from 4x4x4 and from Google's 4x4x16 = 256 example |
| Switches | One OCS per (axis, face position): 48 for a 4x4x4 cube. Every cube takes one `+` and one `-` port on each | Jouppi et al.: 64 blocks, 48 OCSes |
| Port limit | An OCS with `ocs_ports` usable ports serves `ocs_ports // 2` cubes. That group is a **domain**; stitching never crosses one | 136x136 Palomar switch, 128 ports in use and 8 kept for testing and repair (Jouppi et al.). Default 128 |
| Super-slice | Any free healthy cubes in one domain, arranged as a rectangle of cubes, at most `max_cubes_per_axis` long | Parameter. Default 4, to match the 16-chip axes of the static 16x16x16 pod |
| Sub-slice | A job smaller than a cube takes one of the allowed shapes inside one cube. Cubes already shared are filled first | GKE documents 2x2x1, 2x2x2, 2x2x4 and 2x4x4 |
| Ring | Exists on an axis **only if** a closing circuit (last cube `+` to first cube `-`) is configured on every line along it | Derived from the circuit list; never assumed |
| Sub-slice ring | Off by default (`subcube_rings`) | Not documented publicly |
| Spares | `borrow`: swap in any free healthy cube in the domain. `reserve`: hold `spares` cubes out of placement for swaps only | GKE docs say the controller can replace a faulty partition with a healthy spare. The policies are this model's |
| Off-cube sizes | A job above one cube that is not a whole number of cubes is refused, not rounded | Same rule as the static model (ASSUMPTIONS A7) |

The ring rule is checked, not trusted. `stitched_graph` builds the chip graph
from the configured circuits alone, and the registry compares its
breadth-first diameter with the published torus and mesh closed forms (Dally,
1990). Remove one closing bundle and that axis measures as a mesh.

## Results

The static pod is the README's 16-ary 3-cube (4,096 chips). The OCS pod is 64
cubes of 4x4x4 in one 128-port domain (4,096 chips). Each trial draws one
arrival sequence from a seed derived from (workload, occupancy, trial) and
feeds it to both, 60 trials per row. Seed `20261109`.

### 1. Free chips against the largest placeable job

Share of free chips that no single job could use ("overstated"), cube-aligned
jobs of 128--1,024 chips. Each fabric fills toward the same target and stops at
the first request that does not fit, so the occupancy *reached* differs; it is
shown beside each value. "Seam-crossing" is a static torus that may place a
slice across the seam of a ring, which the static model forbids (ASSUMPTIONS
A2):

| Target | Static | Static, seam-crossing | OCS, 4 cubes/axis | OCS, any cube shape |
| ---: | ---: | ---: | ---: | ---: |
| 10% | 8.0% (20.1%) | 7.2% (20.1%) | 10.4% (20.1%) | 0.0% (20.1%) |
| 25% | 13.6% (32.9%) | 12.5% (32.9%) | 8.5% (32.9%) | 0.0% (32.9%) |
| 40% | 19.4% (47.1%) | 18.3% (47.1%) | 3.2% (47.1%) | 0.0% (47.1%) |
| 55% | 28.6% (64.4%) | 26.9% (64.4%) | 4.8% (64.4%) | 0.0% (64.4%) |
| 70% | 32.3% (77.9%) | 27.9% (78.3%) | 1.7% (80.0%) | 0.0% (80.0%) |
| 85% | 30.8% (85.0%) | 28.1% (85.4%) | 1.9% (90.6%) | 0.0% (90.6%) |

Values are overstatement (reached occupancy). At 70% and 85% the OCS pods
reach 2--6 points more occupancy than static, so those rows compare slightly
fuller OCS pods.

With any cube shape allowed, the gap is **zero by construction** for
cube-aligned jobs: any free cube count can be stitched, so the 0% column is a
property of the rule, not a measured advantage. Crossing the seam narrows the
static gap by 0.8--4.4 points; it does not close it. The zero still holds after
a matched third of the jobs leave a pod filled to 85%, which is the test that
actually separates "any free cubes" from "adjacent free cubes" (see the
mutation note below). After those departures the static torus overstates by
43.3% (a gap in 58 of 60 trials), the seam-crossing torus by 35.2% (57 of 60),
OCS capped at 4 cubes per axis by 7.7% (35 of 60), and OCS with any cube shape
by 0.0% (0 of 60). The cube-aligned workload is the best case for OCS; the
rest of this section is the other cases.

**Where it does not help.**

* **A shape menu brings a gap back.** With stitched slices capped at 4 cubes
  per axis, 47 free cubes host a 36-cube job at most, because 37--47 have no
  shape inside 4x4x4 cubes. That is the static gap again, at cube granularity:
  2--10% instead of 8--32%, and *worse* than static on a nearly empty pod
  (10.4% against 8.0% at 10%).
* **Sub-cube jobs bring a gap back.** Add 16- and 32-chip jobs and any shared
  cube is lost to stitching. Overstatement rises with occupancy: 0.5% at 10%,
  5.4% at 85% with any cube shape, and 6--15% with the 4-per-axis cap (static:
  11.2--38.4%; seam-crossing static: 10.6--35.0%). Inside
  a cube the problem is the static one, solved with the static `Fabric`.
* **Sizes that are not whole cubes are refused.** For jobs of 96, 160, 320 and
  640 chips the static torus has a rectangle for every size. The OCS pod
  refuses every 96- and 160-chip request (1.5 and 2.5 cubes), and under the
  4-per-axis cap it refuses all four sizes, because 5 and 10 cubes have no shape
  either. It admitted nothing from that workload. Its 0% overstatement on these
  rows is measured over the 320- and 640-chip jobs it did admit, or over an
  empty pod, and is **not a benefit**: no claim here rests on those rows.
* **The port limit makes domains.** At 64 usable ports a switch serves 32
  cubes, so the largest job is 2,048 chips and stitching cannot use free cubes
  in the other half of the pod: 16.7% overstated at 40% occupancy. At 32 ports
  it is 1,024 chips and 52.8%. The static torus places a 4,096-chip job either
  way.

### 2. What one chip failure costs

A 4,096-chip 16x16x16 slice. Chips the job loses, against two static
baselines. The static model never re-forms a slab across the seam of a ring
(ASSUMPTIONS A2), so its cordon can only pull a face inward. A torus that may
cross its seam drops the failed plane and keeps the other fifteen as one slab
through the wraparound: one plane (256 chips) anywhere, and that axis's ring.
The OCS gets the same option through its closing circuit.

| Location | Static, no seam-crossing | OCS, no spare, no seam-crossing | Static, seam-crossing | OCS, no spare, seam-crossing | OCS + one spare cube |
| --- | ---: | ---: | ---: | ---: | ---: |
| corner | 256 | 256 (cordon) | 256 | 256 (cordon) | 0 |
| edge | 256 | 256 (cordon) | 256 | 256 (cordon) | 0 |
| face | 256 | 256 (cordon) | 256 | 256 (cordon) | 0 |
| interior | 1,280 | 1,024 (re-stitch) | 256 | 256 (cordon) | 0 |
| centre | 2,048 | 1,024 (re-stitch) | 256 | 256 (cordon) | 0 |

* **With a spare cube, the job loses nothing anywhere, on more hardware.**
  The failed cube is swapped out and the slice re-stitched at the same shape,
  so the checkpoint restores. That case runs on a 65th cube and 136 rather
  than 128 ports per switch; no static spare is modelled, so the zero is a cost
  moved into hardware, not removed. The pod loses one cube (64 chips) of
  capacity per failure, with 63 healthy chips idle until repair.
* **A 65th cube needs ports.** At 128 usable ports a switch serves exactly 64
  cubes, so a spare for a whole-pod slice lands in a second domain and cannot
  be swapped in. The table uses all 136 physical ports for that case.
* **Without a spare, cubes beat only a torus that cannot cross its seam.**
  Against the no-seam baseline, re-stitching caps the worst case at 1,024
  (static: 2,048). Once both fabrics may cross the seam, both lose 256 chips
  everywhere and the advantage is gone. The earlier claim that cubes "halve
  the worst case" rested on assumption A2 and is withdrawn as a general claim.

How often the checkpoint-preserving recovery exists, on matched failures
(static: a same-shape move; OCS: a cube to swap in), 40 failures per row:

| Target | Static move | OCS, borrow | OCS, 2 cubes reserved | Reached: static / borrow / reserve |
| ---: | ---: | ---: | ---: | ---: |
| 25% | 40/40 | 40/40 | 40/40 | 32.3% / 32.3% / 32.3% |
| 50% | 39/40 | 40/40 | 40/40 | 58.4% / 58.4% / 58.4% |
| 75% | 29/40 | 40/40 | 40/40 | 79.9% / 81.8% / 81.8% |
| 95% | 14/40 | 30/40 | 40/40 | 88.0% / 92.9% / 88.2% |

At 95% the borrowing pod is 4.9 points fuller than the static one; the
reserving pod reaches about the static level.

**Spares are paid for either way.** Borrowing costs nothing until the pod is
full and then fails a quarter of the time. Reserving two cubes always works and
admitted 192 fewer chips per pod at 95% (3,613 against 3,805).

### 3. Rings and diameter

Slices placed from the sub-cube mix at 85%, 30 matched trials:

| Fabric | 0 rings | 1 | 2 | 3 |
| --- | ---: | ---: | ---: | ---: |
| Static | 131 | 144 | 97 | 0 |
| OCS, rings closed | 131 | 0 | 0 | 246 |
| OCS, rings not closed | 377 | 0 | 0 | 0 |

Every stitched slice gets a ring on all three axes, because the ring's length
is the job's and not the pod's. The 131 slices with no ring under OCS are the
sub-cube jobs, which get no OCS ring under the default policy. If the closing
circuits are not configured, nothing has a ring. Mean diameter, static
against OCS: 12 against 8 hops at 128 chips, 14 against 10 at 256, 17.1
against 12 at 512 and 19 against 16 at 1,024. At 16 and 32 chips the two
fabrics are identical.

## What this does not check

`validation/validate_ocs.py` prints these first on every run:

1. **No measured OCS pod.** Every number above is a model output on synthetic
   arrivals.
2. **The vendor's 5x and 4.5x figures are not inputs and are not checked.**
   There is no time in this model.
3. OCS reconfiguration time, optical insertion loss and switched-hop latency.
   A circuit counts as one hop, like an electrical link.
4. OCS, fibre and link failure. Only chips fail.
5. Twisted tori, and any wiring other than "face position *p* on axis *d* goes
   to switch (*d*, *p*)".
6. Hosts, racks, power and cooling. A cube is the only boundary.
7. Sub-cube rings, which are not documented publicly.
8. GKE's actual list of super-slice shapes. `max_cubes_per_axis` stands in for
   it, and it moves the gap.
9. First-fit at cube granularity, one arrival order. The only departures are
   one matched release of a third of the jobs; there is no arrival process or
   job lifetime. The static model's declined items on time and placement
   policy apply unchanged.
10. **The spare case runs on more hardware.** A 65th cube and all 136 switch
    ports (the 8 the paper keeps for testing and repair). No static spare is
    modelled. Its zero is a cost moved into hardware, not removed.
11. **Two static baselines.** The static model never places or re-forms a
    slice across the seam of a ring (ASSUMPTIONS A2). The registry's failure
    points report that baseline and a seam-crossing one (`slicepacker.seam`);
    its gap points use the first only. `compare.py` measures both.

## Validation

* **Registry:** 18 points (2 calibrated, 9 emergent, 7 sanity) and 11 declined
  items, separate from the static registry. The static registry's 29 points
  and its output are unchanged.
* **Mutations:** twelve. Eleven delete a rule and assert the exact red set;
  one asserts a blind spot.
  - assume every stitched slice wraps: the torus-or-mesh point;
  - never close the ring: four points (with no closing circuit there is no
    seam to cross either);
  - ignore the port limit: four points;
  - no cube swap: five points;
  - no re-stitch: the no-seam worst-case point;
  - stitch only adjacent cubes (delete the OCS): the gap point;
  - ignore the shape cap: three points;
  - stitch cubes that hold sub-slices: three points;
  - hold reserved spares pod-wide, not per domain: the per-domain point;
  - let `copy()` refill a used-up pool: the copy point;
  - no seam-crossing shrink: two points;
  - small jobs never share a cube: **nothing**. No point measures sub-cube
    utilisation, and the test asserts that.
* **A registry weakness found and closed.** The adjacency mutation first
  measured an *empty* red set: the gap point passed with the OCS deleted. With
  first-fit and no departures the free cubes are always consecutive, so "any
  cubes" and "adjacent cubes" never differ. The point now releases a matched
  third of the jobs before it measures, and the experiment reports the same
  case.

## Reproducing

```bash
PYTHONPATH=src:validation python validation/validate_ocs.py   # ~3 s
PYTHONPATH=src:validation python -m pytest tests/test_ocs.py tests/test_ocs_assurance.py
PYTHONPATH=src python experiments/ocs/compare.py              # ~4 min; --quick ~45 s
```

`compare.py --json PATH` writes every table as JSON. It exits 1 if a headline
stops holding.

Make targets: `make validate` runs this registry after the static one,
`make test` collects `tests/test_ocs.py`, `make ocs-smoke` runs
`compare.py --quick` (12 trials instead of 60, ~45 s), and
`make experiments-ocs` runs the full comparison. CI runs the registry and the
quick comparison; the full run stays local.

## For the reviewer

Review the assumptions before the numbers: the cube size, the port limit and
domain rule, the shape cap, the spare policies and the ring rule. Each is a
parameter, and items 1, 2, 5 and 8 above say where each could be wrong. The
no-benefit cases are the result as much as the benefits are.

## Sources

* N. P. Jouppi et al., "TPU v4: An Optically Reconfigurable Supercomputer for
  Machine Learning with Hardware Support for Embeddings," *ISCA 2023*.
  arXiv:2304.01433. Source for the 4x4x4 blocks, the 64-block pod, the 48
  OCSes and the 136x136 Palomar switch with 128 ports in use.
* Google Cloud, "Dynamic slicing" (GKE concepts) and the Slice custom resource
  reference, docs.cloud.google.com/kubernetes-engine/docs/concepts/dynamic-slicing,
  read 9 November 2026. Source for super- and sub-slicing, the sub-slice shapes
  and spare replacement.
* Google, 9 November 2026 announcement of GKE dynamic slicing general
  availability: "up to 5x faster" job start and "up to 4.5x faster" recovery,
  reservation mode only. **Vendor claims, not inputs.**
* W. J. Dally, "Performance Analysis of k-Ary n-Cube Interconnection Networks,"
  *IEEE Trans. Computers* 39(6), 1990. The closed forms the stitched graph is
  checked against (SOURCES S1).
