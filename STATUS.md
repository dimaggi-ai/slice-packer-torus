# Status

**Version 1.0.0. Complete as a model. Unvalidated against any machine.**

## What works

Everything documented in the README, reproducible from a clean checkout with
`make venv && make smoke-test`. 87 unit tests, 19 mutation tests, 24 registry
points, 22 examples pinned to their exit codes, and 3 experiments that exit
non-zero if the figure the README quotes stops holding.

## What this is not

There is no measurement here. No pod, no scheduler, no failure, no tenant. The
two calibrated points pin textbook closed forms for the k-ary n-cube, which
demonstrates that `torus.py` implements the model and demonstrates nothing about
whether the model describes any machine. SOURCES.md and declined items 1 and 2
say this first, before any result.

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
