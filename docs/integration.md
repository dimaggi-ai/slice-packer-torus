# Wiring this to a scheduler

Nothing here talks to hardware, holds state between calls, or performs an
action. It is a set of functions a scheduler can ask questions of. This is where
they fit.

## The one-line change worth making first

Replace the free-chip count in your capacity report:

```python
from slicepacker import Fabric, Topology

fabric = Fabric(Topology.cube(16, 3))          # or your real extents
...
print(f"free      {fabric.free_chips():,}")
print(f"placeable {fabric.largest_placeable():,}")   # <- the honest number
print(f"fragmented {fabric.fragmentation() * 100:.0f}%")
```

If those two numbers are close, nothing else in this repository will surprise
you. If they are far apart, the rest of it is about why.

## Admission

`Fabric.place` is first-fit over shapes ordered by an objective. Two things it
will do that a naive allocator will not:

```python
from slicepacker import NoPlacement, Request

try:
    rect = fabric.place(Request(job_id="pretrain-7", chips=2048,
                                min_torus_dims=2), objective="diameter")
except NoPlacement as exc:
    # The message distinguishes "no shape of this size exists in this pod" from
    # "shapes exist but none lands on free ground". Those need different fixes.
    log.warning("refused: %s", exc)
```

`objective` is one of `diameter`, `bisection`, `torus_dims`. They frequently
disagree; `slicepacker shapes <chips>` shows by how much for a given pod, and
which one your scheduler is implicitly choosing by its tie-breaks.

For a pending queue, `fabric.unservable(demand)` returns which requests cannot
be placed *right now*, each tested independently. It answers "which of these
could I admit", not "can I admit all of them", which is a different and harder
question.

## Tenancy

Isolation needs an owner map alongside the fabric, because a tenant may hold
several jobs:

```python
from slicepacker import Domains, IsolationPolicy, place_isolated, violations

racks = Domains(axis=0, width=1, label="rack")
owners: dict[str, str] = {}

place_isolated(fabric, request, racks, owners, IsolationPolicy(domain_gap=1))
assert not violations(fabric, racks, owners)
```

Call `conflicts(request, pod, racks)` **before** attempting placement. It
returns the reasons a request cannot be both isolated and given what it asked
for --- a contradiction, not a shortage --- and reporting it as a capacity
failure will send an operator hunting for chips that would not have helped.

Set `Domains.axis` and `width` from your own topology-to-power map. Declined
item 11 applies: a rack here is a range of one coordinate, and real power,
cooling and cabling domains do not have to line up with the network.

## Failure

Cordon and reconstitution are deliberately separate calls, and neither mutates
the fabric. A planner that has already acted cannot be reviewed.

```python
from slicepacker import AutonomyPolicy, reconstitution_plan

result = reconstitution_plan(
    fabric, "pretrain-7", failed_coord,
    policy=AutonomyPolicy(max_self_loss_fraction=0.25,
                          allow_reshard=False,
                          allow_eviction=True),
    protected=["serve-a"],          # never drained
)

if result.verdict == "ACT":
    apply(result.best)              # your code, not this package's
elif result.verdict == "PROPOSE":
    escalate(result.explain(), cost=result.cost_of_waiting)
else:                               # REFUSE
    page_someone(result.explain())
```

`cost_of_waiting` is `None` when no autonomous action exists at all. Do not
coerce that to zero: it is the difference between "approval is free" and
"recovery is blocked on a person", and they call for opposite responses.

To apply a chosen candidate yourself:

```python
if result.best.kind.value == "shrink-in-place":
    fabric.allocations[job_id] = result.best.remap.after
else:
    for victim in result.best.remap.victims:
        fabric.release(victim)
    fabric.release(job_id)
    fabric.allocations[job_id] = result.best.remap.after
fabric.unhealthy.add(failed_coord)
```

If `remap.restore_compatible` is false, the job needs a reshard before it can
resume from its last checkpoint. That is the cost that does not appear in a chip
count.

## Exit codes, if you shell out

`0` answered, `1` **refused**, `2` unreadable input. Treat `1` as a result, not
an error --- it is the answer this tool exists to give, and a wrapper that maps
it to a failure will hide exactly the conditions worth seeing.

## What you still have to supply

- Real extents, and which dimensions actually wrap.
- A topology-to-blast-domain map, which is a fact about your building.
- The decision of where L1 ends. The default here is a proposal, not a standard.
- Everything in `ASSUMPTIONS.md`, each of which is a place your machine may
  differ from this model.
