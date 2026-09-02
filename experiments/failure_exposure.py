#!/usr/bin/env python3
"""Where a chip fails decides what it costs, by up to eight times.

A slice is a rectangle and its topology guarantees are guarantees about a
rectangle. Cutting one chip out of the middle leaves neither a rectangle nor
anything a collective library has an algorithm for, so getting back to an honest
shape means pulling a face in past the failure. What that costs depends entirely
on where the chip was.

Exits 1 if the headline stops holding.
"""

from __future__ import annotations

import sys

sys.path.insert(0, "src")

from slicepacker.cordon import cheapest_shrink, exposure  # noqa: E402
from slicepacker.torus import SliceRect  # noqa: E402

SHAPES = [(16, 16, 16), (8, 16, 32), (4, 16, 64), (2, 32, 64), (1, 64, 64)]


def main() -> int:
    rect = SliceRect((0, 0, 0), (16, 16, 16))
    print(f"one chip fails in a {rect.canonical()} slice ({rect.chips:,} chips)")
    print(f"  {'where':<10}{'coordinate':<14}{'chips lost':>12}{'share':>9}")
    rows = [("corner", (0, 0, 0)), ("edge", (0, 0, 8)), ("face", (0, 8, 8)),
            ("interior", (4, 8, 8)), ("centre", (8, 8, 8))]
    for label, coord in rows:
        option = cheapest_shrink(rect, coord)
        print(f"  {label:<10}{str(coord):<14}{option.chips_lost:>12,}"
              f"{option.chips_lost / rect.chips * 100:>8.1f}%")

    ex = exposure(rect)
    print(f"\n  best {ex['best']:,}  median {ex['median']:,}  worst {ex['worst']:,}"
          f"  ->  spread {ex['spread']:.0f}x")

    print("\nthe worst case does not move when you change shape")
    print(f"  {'shape':<16}{'chips':>8}{'best':>8}{'worst':>8}{'worst share':>13}")
    invariant = True
    for shape in SHAPES:
        slice_ = SliceRect((0, 0, 0), shape)
        e = exposure(slice_)
        print(f"  {'x'.join(map(str, shape)):<16}{slice_.chips:>8,}{e['best']:>8,}"
              f"{e['worst']:>8,}{e['worst_fraction'] * 100:>12.0f}%")
        invariant &= e["worst"] == slice_.chips // 2
        invariant &= e["best"] == slice_.chips // max(shape)

    compact, flat = exposure(SliceRect((0, 0, 0), (16, 16, 16))), exposure(
        SliceRect((0, 0, 0), (1, 64, 64)))
    tension = compact["best"] > flat["best"]

    print(f"\n  the worst chip always costs chips/2, whatever the shape: {invariant}")
    print(f"  the compact shape --- the one that wins on diameter --- has the higher")
    print(f"  typical cost ({compact['best']:,} vs {flat['best']:,}): {tension}")

    holds = invariant and tension and ex["spread"] >= 8
    print("\nheadline holds" if holds else "\nHEADLINE NO LONGER HOLDS")
    return 0 if holds else 1


if __name__ == "__main__":
    raise SystemExit(main())
