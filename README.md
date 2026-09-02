# slice-packer-torus

**A pod's free-chip count is not its capacity, and a chip failure does not cost
one chip.**

A job on a torus-connected pod does not need chips. It needs a *rectangle* --- an
axis-aligned sub-grid, because that is the only shape whose diameter, bisection
and collective schedule anyone has computed. That one constraint turns four
ordinary operational questions into different questions than the ones capacity
reports answer:

| The question people ask | The question that decides the outcome |
| --- | --- |
| How many chips are free? | How large a job can still be placed? |
| What does a chip failure cost? | *Where* did the chip fail? |
| Can we recover automatically? | What does waiting for a human cost? |
| Can tenants be isolated? | Which requests make isolation impossible? |

Six models, a command line, and a validation registry that prints what it
declines to check before it prints anything it does check.

**There is no measurement in this repository.** See [What this does not
check](#what-this-does-not-check).

## Six findings

**1. A pod described as a torus hands most jobs a mesh.** A slice inherits a
closed ring in a dimension only if it spans that dimension *completely*. Over
485 slices placed at random on a 16-ary 3-cube, not one received a
three-dimensional torus, and every slice lost at least one ring. The wraparound belongs to the pod; the job gets what is left.

**2. Free chips overstate capacity, and the gap widens as the pod fills.**

```
   occupancy      free  placeable  overstated  trials with a gap
         10%     3,217      2,953          8%           31/60
         40%     2,131      1,696         20%           51/60
         55%     1,547      1,090         30%           55/60
         85%       634        448         29%           41/60
```

**3. One chip failure costs between 6% and 50% of a slice, depending on where
it was.** Getting back to a rectangle means pulling a face in past the failure.
A corner costs one plane; the centre costs half the slice.

```
  where     coordinate      chips lost    share
  corner    (0, 0, 0)              256     6.2%
  face      (0, 8, 8)              256     6.2%
  interior  (4, 8, 8)            1,280    31.2%
  centre    (8, 8, 8)            2,048    50.0%
```

The worst case is **exactly half the slice for every shape**, so packing cannot
buy it down. The best case is `chips / longest axis` --- which means the compact
shape that wins on diameter is the one with the *highest* typical failure cost.
At 4,096 chips in a 64-ary pod, the compact `16x16x16` loses 256 chips to its
cheapest failure and the flat `1x64x64` loses 64.

**4. The option that keeps your checkpoint is the one that runs out first.**
Shrinking in place is cheap in hardware and breaks the rank grid, so the
checkpoint no longer restores. Moving at the same shape keeps the checkpoint and
costs other tenants their chips. Of 120 simulated failures a shrink existed in
all 120 and a same-shape move in only 97.

**5. Isolation has a price, and one request it cannot fill at any price.**
Dedicating a rack per tenant admitted 40,000 chips where an open pod took
75,392. And a job that wants a closed ring must span the axis, which means
touching every rack in it --- so "give me a torus" and "keep me off other
tenants' hardware" are contradictory, not merely competing.

**6. The approval queue becomes the outage exactly when the pod is busiest.**
Confining autonomous action to the failing job means anything that evicts a
neighbour needs a person. Share of failures that reach that boundary:

```
  occupancy   25%: 0/40    50%: 0/40    75%: 5/40    95%: 38/40
```

`cost_of_waiting` prints what the L1 action gives up against the best action
available, and returns `None` --- never zero --- when there is no autonomous
action at all.

## Quickstart

```bash
make venv
make smoke-test          # tests, registry and examples, under a minute
```

```bash
slicepacker example                          # the reference scenario end to end
slicepacker shapes 4096 -k 64 -n 3           # legal shapes, and which objective picks which
slicepacker cordon --shape 16,16,16          # what one chip costs, best to worst
slicepacker pack examples/pod-fragmented.json
slicepacker isolate examples/tenants-contradictory.json
slicepacker reconstitute examples/failure-no-room.json pretrain-7 4,8,8
```

Exit codes are part of the interface: `0` answered, `1` **refused**, `2` the
input could not be read. A refusal is a correct answer, and a scheduler that
treats it as an error papers over the conditions this tool exists to surface.

## The models

| Module | What it decides |
| --- | --- |
| `torus` | k-ary n-cube diameter and bisection; whether a slice inherits a ring |
| `packing` | placement, fragmentation, the largest job still placeable |
| `cordon` | what it costs to get back to a rectangle after a chip dies |
| `embed` | shrink versus move, and the drain a move requires |
| `tenant` | blast-domain isolation, its price, and its contradictions |
| `reconstitute` | what a control plane may do alone, and what waiting costs |

`docs/the-models.md` explains each in prose. `docs/integration.md` covers
wiring it to a scheduler.

## What this does not check

The validation registry prints thirteen declined items above its results on
every run. The first two matter most:

> No measured machine. Every number here is a model output. Nothing has been
> compared against a real torus pod, a real scheduler, or a real failure.

> The calibrated points pin textbook **closed forms**, which are identities
> about an idealised k-ary n-cube. Agreeing with them shows this code implements
> the model correctly. It is not evidence that the model describes any machine,
> and this repository has no empirical anchor of any kind.

Also declined: link failures, routing, time, correlated failure, non-rectangular
allocation, the reshard cost model, the L0/L1 boundary itself, first-fit
placement, what a rack is, and the cost of refusing seam-straddling slices.

The mutation tests in `tests/test_mutations.py` delete machinery on purpose and
assert the exact set of registry points that turns red. Sixteen mutations, a
green unmutated control so no red set can be an artefact, and two tests that
apply a real change and assert the registry does **not** notice --- because it
genuinely cannot. Every asserted red set was measured. Predicting them first was
wrong nine times out of seventeen, and two of those surprises were points that
had been passing on machinery that was no longer there.

## Reproducing

```bash
make test          # 87 unit tests and 19 mutation tests (~4 min: each mutation reruns the registry)
make validate      # 24 registry points and 13 declined items
make examples      # 22 examples, each pinned to its exit code
make experiments   # the three figures quoted above; each exits 1 if it stops holding
```

## Reading order

- `DECISIONS.md` --- fourteen choices, what each bought and cost. Six were
  forced by defects found while building this, and say so.
- `ASSUMPTIONS.md` --- eleven things taken as given.
- `SOURCES.md` --- two, and what they are not.
- `STATUS.md` --- what works, what is missing, what would change the answers.

## Licence

MIT. Copyright (c) 2026 Margaret Nanyonga.
