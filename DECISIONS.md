# Decisions

Each entry is a choice that could reasonably have gone the other way, what it
bought, and what it cost. Five of these were forced by defects found while
building the thing, and those say so.

## D1 --- A slice is a rectangle, and stays one

A job's allocation is an axis-aligned rectangular sub-grid. Nothing in this
repository will produce a topology object for a non-rectangular slice.

**Why.** Every guarantee a slice has --- its diameter, its bisection, whether a
ring closes --- is a guarantee about a rectangle. A rectangle with a chip missing
is not a smaller rectangle; it is a graph with a defect, whose diameter nobody
has computed and whose collective schedule nobody has written. Allowing the
shape to degrade quietly would make every figure this tool prints false in a
direction it could not measure.

**Cost.** Schedulers that accept arbitrary shapes exist. Against those, every
fragmentation number here is an upper bound rather than a measurement, and the
cordon costs in `cordon.py` are the price of a discipline they do not keep.
Declined item 7 says so.

## D2 --- No slice straddles the seam

A ring closes, so a slice occupying `60..3` of a 64-wide axis is a legal
rectangle in the ring's own coordinates. `Fabric.positions` will not offer it.

**Why.** Every scheduler, every operator and every rack label names chips by
absolute position. A slice reported as `60..3` costs more in confusion than it
recovers in packing.

**Cost.** Real packing efficiency, and the amount is not quantified anywhere
here. Declined item 12.

## D3 --- The drain search is exact, or it refuses

`embed.drain_plan` searches subsets of resident jobs smallest-total-chips-first
and raises above `MAX_EXACT_DRAIN_VICTIMS` residents rather than falling back to
a greedy search.

**Why.** A greedy drain evicts the largest neighbour first. The registry
measures what that costs: in 40 of 47 contended cases the greedy planner evicts
more chips than it needs to. A fallback would have hidden that behind an answer
that looks the same.

**Cost.** A hard ceiling on pod occupancy for this function, and an exception
where a lesser tool would return something.

## D4 --- `is_free` tests rectangle overlap, not chips

**Forced by a defect.** The first version walked the candidate rectangle's
coordinates and tested each against the occupied set: O(volume) per candidate
position, called once per position. A capacity report on a 16-ary 3-cube took
minutes and the validation registry could not be run at all. Overlap testing is
O(allocations) and gives the identical answer.

## D5 --- `largest_placeable` enumerates shapes, largest volume first

**Forced by the same defect, twice.** Version one counted downward from the
free-chip count one chip at a time, asking `can_place` each time and repeating
the same position scan thousands of times. Version two enumerated shapes but
built a `SliceRect` for every candidate position, which cost more than the test
it fed. The loop that survives works on raw tuples and is the one place in this
package where speed was allowed to shape the code. Same answers throughout: on
the worked example, free 1,792 / placeable 1,024 / 43% fragmented, before and
after, in 0.13s instead of minutes.

## D6 --- A cordon never deletes an interior plane

`cordon.shrink_options` offers two options per axis: pull in the low face, or
pull in the high face. It does not offer "delete the plane containing the
failure".

**Why.** Removing a plane from the interior splits the rectangle into two
rectangles. That is two slices, and a job holding one slice cannot be handed
two.

**Cost.** A failure at the centre of an axis costs half the slice, where
deleting one plane would have cost one plane. That is the honest price of D1.

## D7 --- Failures are applied in the caller's order, and never double-counted

`cordon.cordon_impact` applies failures one at a time, because shrinking for the
first can move the second outside the slice entirely --- in which case it costs
nothing more.

**Why.** The alternative double-counts, and would report two chips failing in
the same doomed plane as twice the loss.

**Cost.** The result depends on the order given. The docstring says so, and says
the answer should be read as one of several possible orderings.

## D8 --- Anything crossing a tenant boundary is L0

`reconstitute.Policy` bounds what the control plane may do alone: how much of
its own job it may lose, whether it may force a reshard, how many chips it may
move. None of those bounds can make an action that evicts another tenant
autonomous.

**Why.** Evicting a neighbour to heal your own job is a decision with a bill
attached to somebody who is not in the room. No blast-radius bound makes it not
that.

**Cost.** Recovery waits for a person exactly when the pod is busiest --- the
registry measures it, from 0 of 40 failures at 25% occupancy to 38 of 40 at 95%.
`Reconstitution.cost_of_waiting` exists to price that rather than hide it.

## D9 --- Ranking is lexicographic, stated, and replaceable

Candidates are ordered by fewest tenants disturbed, then no reshard, then fewest
chips lost, then fewest chips moved. `reconstitute.rank` takes an explicit key.

**Why.** The ordering is a policy choice, not a fact. A site that disagrees
should be able to say so in code rather than by patching this repository.

## D10 --- `cost_of_waiting` returns `None`, never zero, when nothing is autonomous

**Why.** "Waiting for approval costs nothing" and "there is nothing to wait for"
are opposite situations. Reporting the second as zero would tell an operator the
approval queue is free at precisely the moment it is the outage.

## D11 --- Two `Policy` classes, renamed at the package boundary

`tenant.Policy` and `reconstitute.Policy` are exported as `IsolationPolicy` and
`AutonomyPolicy`.

**Why.** Both names are right in their own module and ambiguous at package
level. Renaming at the boundary beats renaming at the definition, where the
local name would read badly.

## D12 --- The registry is sized to be run, not to be impressive

`POPULATION` is 120, not the 300 the first draft used.

**Why.** The mutation suite reruns the whole registry once per mutation. At 300
the registry took 28 seconds and the mutation suite took eight minutes, which is
a suite that gets run less often. At 120 the findings are unchanged --- 95 of 120
packings overstate capacity where 249 of 300 did, median 27% against 25% --- and
the registry runs in 13 seconds, which puts the whole mutation suite under four
minutes.

## D13 --- This repository has no empirical anchor, and says so first

The calibrated points pin textbook closed forms for the k-ary n-cube. Nothing
here has been compared against a machine.

**Why.** The alternative was to leave the calibrated section looking like
evidence about hardware. A closed form is a mathematical identity: agreeing with
it shows the code implements the model, and shows nothing about whether the
model describes anything. Declined items 1 and 2 lead the registry output, and
`docs/the-models.md` repeats it.

**Cost.** The honest version of this repository is weaker than it would look if
the distinction were left blurred. That is the point.

## D14 --- Every asserted red set was measured, never predicted

Each mutation test asserts the exact set of registry points that turns red, and
each of those sets came out of a run.

**Why.** The first draft asserted predicted sets. Nine of seventeen were wrong,
and the wrongness was informative in both directions. Two mutations reddened
nothing where they should have reddened something, which exposed points that
were passing on machinery no longer present --- the autonomy point that tested
only monotonicity, and the isolation point that accepted a shutdown as a price.
Two others reddened a dozen points each because the mutation was badly aimed
rather than the model badly guarded, and were rewritten. A predicted set that
happens to pass proves the prediction, not the point.

**Cost.** The sets are brittle: adding a registry point can turn an equality
assertion red without anything being wrong. That is the intended trade. A
mutation test that has to be re-measured when the registry changes is a mutation
test somebody has to look at, which beats one that quietly keeps agreeing with
itself. Two mutations are asserted by membership instead: an illegal candidate
shape poisons fifteen points, and naming them would record the blast radius
rather than the cause.
