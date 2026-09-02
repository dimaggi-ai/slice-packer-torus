#!/usr/bin/env python3
"""Keeping tenants out of each other's blast radius costs admitted chips.

Two results. The first is a price: the same demand admitted twice, once open and
once with a dedicated rack per tenant. The second is not a price at all --- it is
a contradiction. A job that wants a closed ring in a dimension must span that
dimension, and spanning it means touching every rack in it, so "give me a torus"
and "keep me off other tenants' hardware" cannot both be honoured.

Exits 1 if the headline stops holding.
"""

from __future__ import annotations

import random
import sys

sys.path.insert(0, "src")

from slicepacker.packing import Request  # noqa: E402
from slicepacker.tenant import Domains, Policy, conflicts, isolation_cost  # noqa: E402
from slicepacker.torus import Topology  # noqa: E402

SEED = 20260902
TRIALS = 30


def main() -> int:
    rng = random.Random(SEED)
    pod = Topology.cube(16, 3)
    racks = Domains(axis=0, width=1, label="rack")

    print(f"pod {'x'.join(map(str, pod.extents))} torus, {racks.count(pod)} racks, "
          f"{TRIALS} random 10-tenant demands")
    print(f"\n  {'policy':<26}{'admitted':>10}{'chips':>10}{'forgone':>10}")

    rows = []
    for label, policy in (("open (no isolation)", None),
                          ("dedicated rack", Policy()),
                          ("dedicated rack + 1 gap", Policy(domain_gap=1)),
                          ("dedicated rack + 2 gap", Policy(domain_gap=2))):
        admitted = chips = forgone = 0
        for _ in range(TRIALS):
            demand = [Request(job_id=f"t{i}", chips=rng.choice([64, 128, 256, 512]),
                              tenant=f"tenant-{i}") for i in range(10)]
            cost = isolation_cost(pod, demand, racks, policy or Policy())
            if policy is None:
                admitted += cost.admitted_open
                chips += cost.chips_open
            else:
                admitted += cost.admitted_isolated
                chips += cost.chips_isolated
                forgone += cost.chips_forgone
        rows.append((label, admitted, chips, forgone))
        print(f"  {label:<26}{admitted:>10}{chips:>10,}"
              + (f"{forgone:>10,}" if policy is not None else f"{'-':>10}"))

    print("\nand one thing isolation cannot buy at any price:")
    contradictory = conflicts(Request(job_id="a", chips=4096, min_torus_dims=3),
                              pod, racks)
    partial = conflicts(Request(job_id="b", chips=1024, min_torus_dims=2), pod, racks)
    for reason in contradictory:
        print(f"  4,096 chips wanting 3 wraparound dimensions: {reason}")
    print(f"  1,024 chips wanting 2 wraparound dimensions: "
          f"{'contradictory' if partial else 'no conflict --- isolation is possible'}")

    costs_something = rows[1][2] < rows[0][2]
    monotone = rows[1][2] >= rows[2][2] >= rows[3][2]
    contradiction_found = bool(contradictory) and not partial

    print(f"\n  isolation admits fewer chips than an open pod: {costs_something}")
    print(f"  a wider gap never admits more: {monotone}")
    print(f"  a full-wraparound request is contradictory, a partial one is not: "
          f"{contradiction_found}")

    holds = costs_something and monotone and contradiction_found
    print("\nheadline holds" if holds else "\nHEADLINE NO LONGER HOLDS")
    return 0 if holds else 1


if __name__ == "__main__":
    raise SystemExit(main())
