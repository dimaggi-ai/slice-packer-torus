"""slice-packer-torus --- what a torus pod can actually still admit.

A pod's free-chip count is not its capacity. A job needs a *rectangle*, and a
pod with a quarter of its chips free may have nowhere to put a job a tenth its
size. Everything here follows from taking that seriously:

* :mod:`slicepacker.torus` --- k-ary n-cube topology, and the rule that decides
  whether a slice inherits a ring: it does, in a dimension, only if it spans
  that dimension completely.
* :mod:`slicepacker.packing` --- placement, fragmentation, and the number a
  capacity report should print instead of free chips: the largest job still
  placeable.
* :mod:`slicepacker.cordon` --- what a single chip failure costs, which depends
  on *where* the chip was: a face failure costs one plane, a centre failure
  costs half the slice.
* :mod:`slicepacker.embed` --- shrink in place (cheap in hardware, breaks the
  checkpoint) versus move (keeps the checkpoint, costs other tenants), and the
  drain needed to make a move possible.
* :mod:`slicepacker.tenant` --- blast-domain isolation, its cost in admitted
  chips, and its flat incompatibility with full wraparound.
* :mod:`slicepacker.reconstitute` --- which of those a control plane may do on
  its own, and what waiting for a person costs.

Nothing here talks to hardware. It is a model you can disagree with in public:
every number it prints comes from a stated rule, and the rules it will not
check are printed too --- run ``python -m slicepacker.cli`` or the validation
registry to see both.
"""

from __future__ import annotations

from .cordon import (
    CordonImpact,
    Response,
    ShrinkOption,
    cheapest_shrink,
    cordon_cost,
    cordon_impact,
    exposure,
    shrink_options,
    worst_position,
)
from .embed import (
    MAX_EXACT_DRAIN_VICTIMS,
    Remap,
    drain_plan,
    options,
    reembed_same_shape,
    reembed_smaller,
)
from .packing import (
    OBJECTIVES,
    Fabric,
    NoPlacement,
    Request,
    best_shape,
    candidate_shapes,
    shape_report,
)
from .reconstitute import (
    Autonomy,
    Candidate,
    Kind,
    Reconstitution,
)
from .reconstitute import Policy as AutonomyPolicy
from .reconstitute import plan as reconstitution_plan
from .reconstitute import rank
from .tenant import (
    Domains,
    IsolationCost,
    Violation,
    conflicts,
    isolated_positions,
    isolation_cost,
    place_isolated,
    tenant_domains,
    violations,
)
from .tenant import Policy as IsolationPolicy
from .torus import Coord, SliceRect, Topology

__version__ = "1.1.0"

#: Alias kept because ``options`` is ambiguous once imported at package level.
failure_options = options

__all__ = [
    "__version__",
    # topology
    "Topology", "SliceRect", "Coord",
    # packing
    "Fabric", "Request", "NoPlacement", "OBJECTIVES",
    "candidate_shapes", "shape_report", "best_shape",
    # cordon
    "Response", "ShrinkOption", "CordonImpact",
    "shrink_options", "cheapest_shrink", "cordon_cost", "cordon_impact",
    "exposure", "worst_position",
    # embed
    "Remap", "MAX_EXACT_DRAIN_VICTIMS",
    "reembed_same_shape", "reembed_smaller", "drain_plan",
    "options", "failure_options",
    # tenant
    "Domains", "IsolationPolicy", "Violation", "IsolationCost",
    "tenant_domains", "violations", "conflicts",
    "isolated_positions", "place_isolated", "isolation_cost",
    # reconstitute
    "Autonomy", "Kind", "Candidate", "Reconstitution", "AutonomyPolicy",
    "reconstitution_plan", "rank",
]
