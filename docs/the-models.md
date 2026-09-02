# The models

Six of them. Each is a rule you can disagree with, stated precisely enough that
disagreeing is possible.

---

## 1. Topology: a slice inherits a ring only by spanning

A pod is a k-ary n-cube: `extents` per dimension, and a flag per dimension
saying whether it wraps. The closed forms are the textbook ones --- diameter
`n*floor(k/2)` for a torus and `n*(k-1)` for a mesh, bisection `2k^(n-1)` and
`k^(n-1)` --- and `torus.py` checks them against breadth-first search and exact
bipartition enumeration on small pods, because a closed form that is merely
self-consistent is worth nothing.

The rule that matters is not in the textbooks, because it is about allocation
rather than topology:

> A slice inherits the wraparound in a dimension **only if it spans that
> dimension completely.**

A ring closes when the last chip is adjacent to the first. Take half the ring
and the two ends are not adjacent to anything --- they are ends. So a `8x16x16`
slice of a `16x16x16` torus is a torus in two dimensions and a line in the
third, and its diameter is not the pod's diameter scaled down.

The consequence is measured rather than asserted. Over 485 slices placed at
random on a 16-ary 3-cube, **not one** received a three-dimensional torus, and
every slice lost at least one ring. A pod bought as a torus hands almost every
job a mesh in at least one dimension, and the only job that gets the full torus
is the one that takes the whole pod.

Extent 1 and extent 2 cannot wrap at all --- at 1 the wraparound is a self-loop
and at 2 it duplicates the link already there --- and `Topology` refuses to be
constructed that way rather than modelling a ring that is not one.

---

## 2. Packing: capacity is the largest job you can still place

A pod reports free chips. A job needs a rectangle. These are different
quantities and the difference grows as the pod fills:

```
   occupancy      free  placeable  overstated
         10%     3,217      2,953          8%
         40%     2,131      1,696         20%
         55%     1,547      1,090         30%
```

`Fabric.largest_placeable()` is the number a capacity report should print.
`Fabric.fragmentation()` is the fraction of free chips that cannot join any
single placement --- zero when the free space is one usable rectangle, one when
the pod has free chips and can admit nothing at all.

Which shape a job gets depends on what it optimised for, and the three
objectives on offer disagree in 12 of 18 (pod, size) pairs tested. At 4,096
chips in a 64-ary 3-cube:

| objective | shape | diameter | bisection | wraparound dims |
| --- | --- | --- | --- | --- |
| `diameter` | `16x16x16` | 45 | 256 | 0 |
| `torus_dims` | `1x64x64` | 64 | 128 | 2 |

Asking for wraparound gets you a worse network than asking for compactness. The
disagreement is pod-dependent: at a 16-ary pod the same three objectives all
pick the same shape, so a demonstration built on the small pod would prove
nothing --- which is why the registry measures *where* they disagree instead of
asserting *that* they do.

---

## 3. Cordon: where the chip failed decides what it costs

One chip fails. Cordoning that chip leaves a rectangle with a hole, which is not
a smaller rectangle. It is a graph with a defect: rings that no longer close,
shortest paths that detour, and a shape no collective library has an algorithm
for. Every published figure about that slice is now false, in a direction nobody
has measured.

So the honest cordon is bigger than the failure. To get back to a rectangle you
pull a face in past the failed chip --- and you cannot simply delete the plane
containing it, because removing an interior plane splits the rectangle into two
rectangles, and a job holding one slice cannot be handed two.

That makes position, not failure, the cost driver:

```
  corner    (0, 0, 0)     256 chips     6.2% of the slice
  face      (0, 8, 8)     256 chips     6.2%
  interior  (4, 8, 8)   1,280 chips    31.2%
  centre    (8, 8, 8)   2,048 chips    50.0%
```

Two exact results follow, and both are checked:

- **The worst case is exactly `chips / 2`, for every rectangular shape.** The
  worst chip sits at the centre of every axis, where each axis costs half. No
  packing decision reduces it.
- **The best case is `chips / longest axis`.** A long axis gives you a thin
  plane to sacrifice.

Which produces a conflict nobody prices: the compact shape that minimises
diameter is the shape with no long axis, so it has the *highest* cheap-failure
cost. At 4,096 chips, `16x16x16` loses 256 chips to its cheapest failure and
`1x64x64` loses 64. The conflict vanishes where the compact shape already spans
an axis --- at 8,192 chips the diameter-optimal shape is `8x16x64`, which gets
both the ring and the thin plane.

---

## 4. Embed: shrink is cheap in hardware, move is cheap in software

After the cordon there are two honest responses, and they fail in opposite
directions.

**Shrink in place.** Nothing moves, no other tenant is touched. But the logical
rank grid changes shape, so a checkpoint written by the old grid does not
restore onto the new one without a reshard, and the collective schedule the job
was tuned for is gone.

**Re-embed at the same shape.** The rank grid is untouched, so the checkpoint
restores. But every chip changes physical identity, and on a busy fabric there
is nowhere to put it without evicting somebody.

Capacity planners price the first and ignore the second, because the first shows
up as chips and the second shows up as a training run that will not restart. Of
120 simulated failures, a shrink existed in all 120 and a same-shape move in
only 97: **the option that preserves your checkpoint is the one that disappears
as the pod fills.**

`drain_plan` prices the third thing --- the chips belonging to *other* jobs that
must be evicted to make a same-shape move possible. It searches subsets exactly,
smallest total first, and refuses above sixteen residents rather than falling
back to a greedy search. That refusal is load-bearing: a greedy planner evicting
the largest neighbour first over-evicts in 40 of 47 contended cases.

---

## 5. Tenancy: isolation has a price, and one thing it cannot buy

A blast domain is a set of chips that leave service together: a rack on one
breaker, a row behind one CDU, a cage a technician opens. Isolation means two
tenants never share one.

The price is measurable. Admitting the same demand twice, open and with a
dedicated rack per tenant:

```
  open (no isolation)         299 jobs    75,392 chips
  dedicated rack              166 jobs    40,000 chips
  dedicated rack + 1 gap      132 jobs    32,576 chips
  dedicated rack + 2 gap      102 jobs    22,528 chips
```

And then there is the thing no price buys. A job that wants a closed ring in a
dimension must span that dimension, and spanning it means touching every blast
domain along it. So:

> A request for a full wraparound dimension **cannot** be isolated in that
> dimension.

`conflicts()` returns that before any placement is attempted, because a
contradiction in the request is not a capacity problem and must not be reported
as one. A scheduler that accepts both requirements is going to silently drop one
of them.

---

## 6. Reconstitution: who is allowed to fix it, and what waiting costs

Every option above is already priced. What remains is the question that actually
delays recovery: may the control plane act, or does this need a person?

The rule is narrow on purpose. An action is autonomous (**L1**) only when it is
confined to the job that suffered the failure and stays inside a declared bound
on self-inflicted loss, reshard and chips moved. Anything reaching across a
tenant boundary is **L0** --- proposed by the planner, approved by a person.
That is not a safety ritual: evicting a neighbour to heal your own job is a
decision with a bill attached to somebody who is not in the room, and no bound
on blast radius makes it not that.

Which means the boundary bites hardest when you can least afford it:

```
  occupancy   25%: 0/40    50%: 0/40    75%: 5/40    95%: 38/40
```

`Reconstitution.cost_of_waiting` is the output nobody else prints: the
difference between the best action available without a human and the best action
available at all. Zero means the escalation is free. It returns `None`, never
zero, when there is no autonomous action --- because "waiting costs nothing" and
"there is nothing to wait for" are opposite situations, and reporting the second
as the first tells an operator the approval queue is free at the moment it is
the outage.

Ranking is lexicographic --- fewest tenants disturbed, then no reshard, then
fewest chips lost, then fewest moved --- and that ordering is a policy choice,
not a fact. `rank()` takes an explicit key so a site that disagrees can say so
in code.

---

## 7. Hazard: when a chip earns eviction, measured on a fleet that existed

`hazard.py` is the one module that reads a measurement: the public Titan GPU
lifetime dataset (Ostrouchov et al., SC '20; `make data` fetches and SHA-pins
it). From 30,207 GPUs and 100,889 GPU-years it computes cohort death rates by
batch and by cage --- the cabinet's vertical cooling position --- and an
age-resolved hazard with the exposure clamped to each bucket, which is the part
survival accounting is usually wrong about.

Two decisions come out. `evict_or_ride` prices a preemptive drain against
`p_fail x unplanned reconstitution` over one window (DECISIONS D16): on Titan's
numbers even the worst cohort rides unless the drain is nearly free, because
the break-even hazard sits nearly nine times above anything the fleet
measured. `split_rank_recall` uses the same estimate for placement instead ---
rank held-out chips by cohort hazard learned on the other half of the fleet ---
and the top 30% of the ranking holds 55% of the held-out deaths. Which is the
decision Titan's operators actually shipped: reliability-aware placement, not
preemptive eviction.

The rates are Titan's own and do not transfer (ASSUMPTIONS A12). The shape ---
cohort hazard beats fleet-uniform, position in the cooling path is a covariate
--- is the claim, and it is exactly the W10 telemetry-fusion claim in miniature.

## What none of this is

There is exactly one measurement in this repository, and section 7 holds all
of it: a failure history. It anchors death rates, not geometry. The two
closed-form calibrated points pin mathematical identities about an idealised
k-ary n-cube: agreeing with them shows the code implements the model and shows
nothing about whether the model describes a machine.

Every other number above --- fragmentation, cordon cost, isolation price, the
autonomy boundary --- is a model output derived from the rules stated here, and
is offered as something to disagree with rather than something to cite.
