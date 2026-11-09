# OCS cubes: what optical stitching removes, and what it does not

Every other model in this repository assumes one static torus. This one models
a pod built from **cubes joined by optical circuit switches (OCS)**, and
compares it with the static torus on matched pods, arrivals, failures and
seeds. Module: `src/slicepacker/ocs.py`. Experiment:
`experiments/ocs/compare.py`. Registry: `validation/validate_ocs.py`. Tests and
mutations: `tests/test_ocs.py`.

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
and one chip failure costs 6--50% of a slice depending on where it is.

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
jobs of 128--1,024 chips:

| Occupancy | Static | OCS, 4 cubes/axis | OCS, any cube shape |
| ---: | ---: | ---: | ---: |
| 10% | 8.0% | 10.4% | 0.0% |
| 25% | 13.6% | 8.5% | 0.0% |
| 40% | 19.4% | 3.2% | 0.0% |
| 55% | 28.6% | 4.8% | 0.0% |
| 70% | 32.3% | 1.7% | 0.0% |
| 85% | 30.8% | 1.9% | 0.0% |

With any cube shape allowed, the gap is **zero by construction** for
cube-aligned jobs: any free cube count can be stitched. That still holds after
a matched third of the jobs leave a pod filled to 85%, which is the test that
actually separates "any free cubes" from "adjacent free cubes" (see the
mutation note below). After those departures the static torus overstates by
43.3% (a gap in 58 of 60 trials), OCS capped at 4 cubes per axis by 7.7% (35
of 60), and OCS with any cube shape by 0.0% (0 of 60). The cube-aligned workload is the best case for OCS; the
rest of this section is the other cases.

**Where it does not help.**

* **A shape menu brings a gap back.** With stitched slices capped at 4 cubes
  per axis, 47 free cubes host a 36-cube job at most, because 37--47 have no
  shape inside 4x4x4 cubes. That is the static gap again, at cube granularity:
  2--10% instead of 8--32%, and *worse* than static on a nearly empty pod
  (10.4% against 8.0% at 10%).
* **Sub-cube jobs bring a gap back.** Add 16- and 32-chip jobs and any shared
  cube is lost to stitching. Overstatement rises with occupancy: 0.5% at 10%,
  5.4% at 85% with any cube shape, and 6--15% with the 4-per-axis cap. Inside
  a cube the problem is the static one, solved with the static `Fabric`.
* **Sizes that are not whole cubes are refused.** For jobs of 96, 160, 320 and
  640 chips the static torus has a rectangle for every size. The OCS pod
  refuses every 96- and 160-chip request (1.5 and 2.5 cubes), and under the
  4-per-axis cap it refuses all four sizes, because 5 and 10 cubes have no shape
  either. It admitted nothing from that workload.
* **The port limit makes domains.** At 64 usable ports a switch serves 32
  cubes, so the largest job is 2,048 chips and stitching cannot use free cubes
  in the other half of the pod: 16.7% overstated at 40% occupancy. At 32 ports
  it is 1,024 chips and 52.8%. The static torus places a 4,096-chip job either
  way.

### 2. What one chip failure costs

A 4,096-chip 16x16x16 slice. Chips the job loses:

| Location | Static | OCS + one spare cube | OCS, no spare |
| --- | ---: | ---: | ---: |
| corner | 256 | 0 | 256 (cordon) |
| edge | 256 | 0 | 256 (cordon) |
| face | 256 | 0 | 256 (cordon) |
| interior | 1,280 | 0 | 1,024 (re-stitch) |
| centre | 2,048 | 0 | 1,024 (re-stitch) |

* **With a spare cube in the domain, the cost is zero everywhere.** The failed
  cube is swapped out and the slice re-stitched at the same shape, so the
  checkpoint restores. The cost moves out of the job and into the pod: one cube
  (64 chips) of capacity per failure, with 63 healthy chips idle until repair.
* **A 65th cube needs ports.** At 128 usable ports a switch serves exactly 64
  cubes, so a spare for a whole-pod slice lands in a second domain and cannot
  be swapped in. The table uses all 136 physical ports for that case.
* **Without a spare, cubes halve the worst case and leave the best case
  alone.** Dropping one layer of cubes and re-stitching costs a quarter of the
  slice wherever the failure is. A corner failure still costs exactly what it
  costs the static torus, and the face pulled in loses its ring.

How often the checkpoint-preserving recovery exists, on matched failures
(static: a same-shape move; OCS: a cube to swap in), 40 failures per row:

| Occupancy | Static move | OCS, borrow | OCS, 2 cubes reserved |
| ---: | ---: | ---: | ---: |
| 25% | 40/40 | 40/40 | 40/40 |
| 50% | 39/40 | 40/40 | 40/40 |
| 75% | 29/40 | 40/40 | 40/40 |
| 95% | 14/40 | 30/40 | 40/40 |

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

## Validation

* **Registry:** 16 points (2 calibrated, 9 emergent, 5 sanity) and 9 declined
  items, separate from the static registry. The static registry's 29 points
  and its output are unchanged.
* **Mutations:** nine. Eight delete a rule and assert the exact red set; one
  asserts a blind spot.
  - assume every stitched slice wraps: the torus-or-mesh point;
  - never close the ring: three points;
  - ignore the port limit: three points;
  - no cube swap: three points;
  - no re-stitch: the worst-case point;
  - stitch only adjacent cubes (delete the OCS): the gap point;
  - ignore the shape cap: three points;
  - stitch cubes that hold sub-slices: three points;
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
PYTHONPATH=src:validation python -m pytest tests/test_ocs.py  # ~30 s
PYTHONPATH=src python experiments/ocs/compare.py              # ~3 min; --quick ~40 s
```

`compare.py --json PATH` writes every table as JSON. It exits 1 if a headline
stops holding.

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
