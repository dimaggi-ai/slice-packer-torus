#!/usr/bin/env python3
"""Free chips are not capacity, and the gap widens as the pod fills.

A pod reports free chips. A job needs a rectangle. This walks a 16-ary 3-cube
from empty to nearly full and prints, at each step, what the free-chip count
claims and what could actually be admitted.

Exits 1 if the headline stops holding.
"""

from __future__ import annotations

import random
import sys

sys.path.insert(0, "src")

from slicepacker.packing import Fabric, NoPlacement, Request  # noqa: E402
from slicepacker.torus import Topology  # noqa: E402

SEED = 20260902
TRIALS = 60
SIZES = [128, 256, 512, 1024]


def main() -> int:
    rng = random.Random(SEED)
    pod = Topology.cube(16, 3)
    print(f"pod {'x'.join(map(str, pod.extents))} torus, {pod.chips:,} chips, "
          f"{TRIALS} random arrival orders per occupancy")
    print(f"\n  {'occupancy':>10}{'free':>10}{'placeable':>11}{'overstated':>12}"
          f"{'trials with a gap':>19}")

    rows = []
    for target in (0.10, 0.25, 0.40, 0.55, 0.70, 0.85):
        frees, placeables, gapped = [], [], 0
        for _ in range(TRIALS):
            fabric = Fabric(pod)
            n = 0
            while fabric.allocated_chips() < target * pod.chips:
                try:
                    fabric.place(Request(job_id=f"j{n}", chips=rng.choice(SIZES)))
                    n += 1
                except NoPlacement:
                    break
            free, placeable = fabric.free_chips(), fabric.largest_placeable()
            frees.append(free)
            placeables.append(placeable)
            if placeable < free:
                gapped += 1
        free_avg = sum(frees) / len(frees)
        place_avg = sum(placeables) / len(placeables)
        overstated = 1 - place_avg / free_avg if free_avg else 0.0
        rows.append((target, free_avg, place_avg, overstated, gapped))
        print(f"  {int(target * 100):>9}%{free_avg:>10,.0f}{place_avg:>11,.0f}"
              f"{overstated * 100:>11.0f}%{gapped:>13}/{TRIALS}")

    widening = rows[-1][3] > rows[0][3]
    always_short = all(p <= f for _, f, p, _, _ in rows)
    somewhere_short = any(g > TRIALS // 2 for *_, g in rows)

    print(f"\n  the gap widens with occupancy: {widening}")
    print(f"  placeable never exceeds free: {always_short}")
    print(f"  a majority of packings are short at some occupancy: {somewhere_short}")

    holds = widening and always_short and somewhere_short
    print("\nheadline holds" if holds else "\nHEADLINE NO LONGER HOLDS")
    return 0 if holds else 1


if __name__ == "__main__":
    raise SystemExit(main())
