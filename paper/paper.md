# Slice-Packing a Torus Pod: Rectangles, Blast Radii, and One Measured Fleet

**Margaret Nanyonga**, DIMAGGI AI

> Staged whitepaper. The claims, figures, and numbers here are reproduced
> by the accompanying open-source repository
> (`dimaggi-ai/slice-packer-torus`, MIT).

## Abstract

A job on a torus-connected pod does not need chips; it needs an
axis-aligned rectangle, because that is the only shape whose diameter,
bisection, and collective schedule anyone has computed. That constraint
turns familiar capacity questions into different questions, and we report
seven findings from six geometric models and one measured failure history.
**(1)** A pod described as a torus hands most jobs a mesh: over 485 random
placements on a 16-ary 3-cube, no slice received a three-dimensional torus
and every slice lost at least one ring — the wraparound belongs to the
pod. **(2)** Free chips overstate placeable capacity by 20–30% through the
mid-occupancy range, and the gap widens as the pod fills. **(3)** One chip
failure costs between 6% and 50% of a slice depending on where it lands;
the worst case is exactly half the slice for every shape, so packing
cannot buy it down, and the compact shape that wins on diameter has the
*highest* typical failure cost. **(4)** After a failure, the shrink that
is always available breaks the rank grid and orphans the checkpoint, while
the same-shape move that keeps the checkpoint existed in only 97 of 120
simulated failures. **(5)** Isolation has a price — a rack-per-tenant pod
admitted 40,000 chips where an open pod took 75,392 — and one request it
cannot fill at any price: a closed ring requires spanning the axis, so
"give me a torus" and "keep me off other tenants' hardware" are
contradictory rather than competing. **(6)** Confining autonomous recovery
to the failing job sends 38 of 40 failures to a human approval queue at
95% occupancy, versus 0 of 40 at half load: the queue becomes the outage
exactly when the pod is busiest. **(7)** On the one measured fleet — the
public Titan GPU lifetime dataset, 30,207 GPUs and 100,889 GPU-years —
hazard-ranked *placement* pays and hazard-ranked *eviction* does not:
ranking held-out chips by cohort hazard learned on the other half of the
fleet puts 55% of deaths in the top 30% (lift 1.84×), yet the break-even
hazard for a preemptive drain at a 90-day window and a 4:1 cost ratio is
1.17 per GPU-year — nearly nine times anything the fleet ever measured.
Titan's operators reached the same verdict in production.

## 1. Model

Six models cover the allocation layer — legal shapes and their graph
properties, first-fit packing, the cordon around a failure, re-embedding
after shrink, tenancy isolation, and reconstitution — and a seventh reads
the failure history: cohort rates, an age-binned hazard with
exposure clamped at bucket boundaries, the evict-or-ride inequality, and a
split-sample ranking evaluation. The dataset is fetched and SHA-pinned,
never vendored — upstream publishes it with a citation request and no
license grant — and a missing file turns the registry's Titan points red
rather than skipped, so a green run means the anchor was measured.

## 2. Validation

The registry holds twenty-nine points — five calibrated, twelve emergent,
twelve sanity — and prints sixteen declined items before any result. The
suite is 104 unit tests, twenty-two mutation tests, and twenty-four
examples. Mutation red sets are measured, not predicted, and one
measurement earned its keep: the mutation that drops the hazard exposure
clamp was measured to slip past every ordering assertion — the mutated
curve still climbs — so the registry pins the mid-life magnitude
(0.10–0.14 per GPU-year), and the mutation now reddens exactly that point.
The geometry has no empirical anchor; the failure history does, and the
registry says which is which on every run.

## 3. What a skeptic should attack

Only chip failures are modelled; a failed link breaks a ring without
removing a chip and every shrink computed here would miss it. There is no
time — every fragmentation figure is a snapshot after one arrival order —
and no routing, so diameter and bisection are static properties, not
achieved throughput. The rectangle constraint is assumed, not derived;
against a scheduler that accepts irregular allocations these numbers are
upper bounds. Titan's rates are Titan's own — one chip generation, one
machine, one decade — and do not transfer (the repository's A12); the
transferable claim is the shape, cohort-beats-uniform, not any rate. And
the paper's own filtered event counts could not be reproduced from the
published summary file, so they are declined rather than approximated.

## 4. Conclusion

The allocation layer of a torus pod is where geometry quietly converts
hardware into less capacity than the inventory shows: rings become meshes,
free chips become unplaceable, a corner failure and a centre failure
differ by a factor of eight. The one measured fleet adds the operational
verdict: spend hazard estimates on placement, not eviction — which is what
Titan itself did, re-cutting the job mix onto reliable nodes rather than
draining ahead of failures it could rank but not schedule around.
