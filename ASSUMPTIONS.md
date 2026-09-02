# Assumptions

Things this repository takes as given. Each one is a place where a real machine
may differ, and where it does, the numbers change.

**A1 --- Chips are interchangeable.** One accelerator is like another: same
memory, same links, same speed. A pod with mixed generations has a placement
problem this does not model.

**A2 --- No slice straddles the seam.** A rectangle's origin plus its extent
stays inside the pod's bounds, even in a dimension that wraps. See DECISIONS D2.

**A3 --- A blast domain is a range of one coordinate.** `tenant.Domains(axis,
width)` partitions the pod along a single axis. Real power, cooling and cabling
domains do not have to line up with the network topology, and frequently do not.

**A4 --- Failures are chip-level, independent, and instantaneous.** A chip is
either in service or not. Correlated failure --- a breaker, a CDU, a technician
with a cart --- is what the blast-domain model is *for*, and nothing here
generates it.

**A5 --- The rank grid is the slice shape.** A checkpoint restores if and only
if the new slice has the identical extent tuple. Real reshard cost depends on
the parallelism strategy and is not a step function; this treats it as one.

**A6 --- Placement is first-fit.** The first free position of the first
acceptable shape wins. A scheduler with lookahead would fragment less, so every
fragmentation figure describes first-fit rather than the achievable minimum.

**A7 --- Requests are for exact chip counts.** A count with no rectangle in the
pod is refused, not rounded up. In practice it would be rounded, and the
rounding waste is not modelled.

**A8 --- There is no time.** Everything here is a snapshot. Jobs in a real pod
arrive and leave, and a steady-state fragmentation figure is a different and
harder quantity than the one computed here.

**A9 --- Links do not fail on their own.** Only chips leave service. A failed
link breaks a ring without removing a chip, and every shrink computed here would
miss it entirely.

**A10 --- Routing is not modelled.** Diameter and bisection are static graph
properties. What a collective achieves depends on the routing algorithm,
deadlock avoidance and the traffic pattern, none of which appear here.

**A11 --- A tenant is a string.** There are no quotas, no fair-share, no
accounting. `Request.priority` is carried and not yet used by any placement
decision.
