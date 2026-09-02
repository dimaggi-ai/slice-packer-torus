# Status

**Version 1.1.0. Complete as a model. The failure history is anchored to a measured fleet (Titan, SC '20); the geometry remains unvalidated against any machine.**

## What works

Everything documented in the README, reproducible from a clean checkout with
`make venv && make data && make smoke-test`. 104 unit tests, 22 mutation
tests, 29 registry points, 24 examples pinned to their exit codes, and 3
experiments that exit
non-zero if the figure the README quotes stops holding.

## What this is not

There is exactly one measurement here, and it measures failures, not packing:
the Titan GPU lifetime dataset behind `hazard.py` (fetched and SHA-pinned, not
vendored). No pod geometry, no scheduler, no tenant has met a machine. The two
closed-form calibrated points pin textbook identities for the k-ary n-cube,
which demonstrates that `torus.py` implements the model and demonstrates
nothing about whether the model describes any machine --- and Titan's rates do
not transfer to other machines (ASSUMPTIONS A12). SOURCES.md and declined items
1, 2 and 15 say this first, before any result.

## Known gaps, in the order they would matter

1. **Link failures.** Only chips leave service. A failed link breaks a ring
   without removing a chip, and every shrink computed here would miss it.
2. **Time.** Every figure is a snapshot after one arrival order. Steady-state
   fragmentation under arrivals and departures is a different quantity.
3. **Correlated failure.** The blast-domain model exists to describe it and does
   not generate it.
4. **Routing.** Diameter and bisection are static graph properties; achieved
   collective bandwidth is not.
5. **Non-rectangular allocation.** Assumed away (DECISIONS D1), which makes
   every fragmentation number an upper bound against schedulers that allow it.

## What would change the answers

A pod with a documented slice API and a failure log. Given those, the cordon
costs, the fragmentation curve and the autonomy boundary all become measurable
rather than modelled, and the first two calibrated points stop being the only
ones.
