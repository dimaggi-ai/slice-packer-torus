"""Command line for slice-packer-torus.

Exit codes are part of the interface, and the middle one is the point:

* ``0`` --- the question was answered.
* ``1`` --- **refused**. The fabric or the policy says no. This is a correct
  answer, not a failure, and a scheduler that treats it as an error will paper
  over exactly the conditions this tool exists to surface.
* ``2`` --- the input could not be read, or contradicts itself.

Run ``python -m slicepacker.cli example`` for the reference scenario.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .cordon import cheapest_shrink, cordon_impact, exposure, worst_position
from .embed import drain_plan, options as failure_options, reembed_same_shape
from .packing import (
    Fabric,
    NoPlacement,
    OBJECTIVES,
    Request,
    candidate_shapes,
    shape_report,
)
from .reconstitute import Policy as AutonomyPolicy
from .reconstitute import plan as reconstitution_plan
from .tenant import Domains, IsolationCost
from .tenant import Policy as IsolationPolicy
from .tenant import conflicts, isolation_cost, place_isolated, violations
from .torus import Coord, SliceRect, Topology

#: Imported lazily inside the parser to avoid a circular import at module
#: load time: the package __init__ imports this module.

OK, REFUSED, UNREADABLE = 0, 1, 2

#: The scenario every doc example is written against: a 16-ary 3-cube torus,
#: 4,096 chips, one rack per value of axis 0.
REFERENCE = {
    "pod": {"k": 16, "n": 3, "wrap": True},
    "domains": {"axis": 0, "width": 1, "label": "rack"},
    "demand": [
        {"job_id": "pretrain-7", "chips": 2048, "tenant": "research"},
        {"job_id": "eval-2", "chips": 512, "tenant": "research"},
        {"job_id": "serve-a", "chips": 512, "tenant": "platform"},
        {"job_id": "batch-9", "chips": 256, "tenant": "analytics"},
    ],
}


class Unreadable(Exception):
    """The input is not a scenario this tool can act on."""


# -- input ------------------------------------------------------------------


def _load(path: Optional[str]) -> Dict[str, Any]:
    if path in (None, "-"):
        text = sys.stdin.read()
    else:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                text = handle.read()
        except OSError as exc:
            raise Unreadable(str(exc)) from exc
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise Unreadable(f"not JSON: {exc}") from exc
    if not isinstance(doc, dict):
        raise Unreadable("the top level of a scenario must be an object")
    return doc


def _pod(doc: Dict[str, Any]) -> Topology:
    spec = doc.get("pod")
    if not isinstance(spec, dict):
        raise Unreadable("a scenario needs a 'pod' object")
    try:
        if "extents" in spec:
            wrap = spec.get("wrap", True)
            extents = tuple(int(x) for x in spec["extents"])
            if isinstance(wrap, bool):
                wrap = (wrap,) * len(extents)
            return Topology(extents, tuple(bool(w) for w in wrap))
        return Topology.cube(int(spec["k"]), int(spec["n"]),
                             wrap=bool(spec.get("wrap", True)))
    except (KeyError, TypeError, ValueError) as exc:
        raise Unreadable(f"bad pod: {exc}") from exc


def _requests(doc: Dict[str, Any], field: str = "demand") -> List[Request]:
    raw = doc.get(field, [])
    if not isinstance(raw, list):
        raise Unreadable(f"'{field}' must be a list")
    out: List[Request] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise Unreadable(f"{field}[{i}] must be an object")
        try:
            out.append(Request(
                job_id=str(item["job_id"]),
                chips=int(item["chips"]),
                shape=tuple(item["shape"]) if item.get("shape") else None,
                min_torus_dims=int(item.get("min_torus_dims", 0)),
                tenant=str(item.get("tenant", "")),
                priority=int(item.get("priority", 0)),
            ))
        except (KeyError, TypeError, ValueError) as exc:
            raise Unreadable(f"{field}[{i}]: {exc}") from exc
    return out


def _fabric(doc: Dict[str, Any]) -> Tuple[Fabric, Dict[str, str]]:
    pod = _pod(doc)
    fabric = Fabric(pod)
    owners: Dict[str, str] = {}
    try:
        for coord in doc.get("unhealthy", []):
            fabric.unhealthy.add(tuple(int(c) for c in coord))
        for job_id, rect in (doc.get("allocations") or {}).items():
            fabric.allocations[job_id] = SliceRect(
                tuple(int(c) for c in rect["origin"]),
                tuple(int(c) for c in rect["extent"]),
            )
            if rect.get("tenant"):
                owners[job_id] = str(rect["tenant"])
    except (KeyError, TypeError, ValueError) as exc:
        raise Unreadable(f"bad allocations: {exc}") from exc
    fabric.__post_init__()
    return fabric, owners


def _domains(doc: Dict[str, Any]) -> Domains:
    spec = doc.get("domains") or {"axis": 0, "width": 1, "label": "rack"}
    try:
        return Domains(axis=int(spec["axis"]), width=int(spec.get("width", 1)),
                       label=str(spec.get("label", "rack")))
    except (KeyError, TypeError, ValueError) as exc:
        raise Unreadable(f"bad domains: {exc}") from exc


def _coord(text: str, pod: Topology) -> Coord:
    try:
        coord = tuple(int(p) for p in text.replace(" ", "").split(","))
    except ValueError as exc:
        raise Unreadable(f"'{text}' is not a coordinate") from exc
    if len(coord) != pod.ndim:
        raise Unreadable(f"{coord} has {len(coord)} dimension(s), pod has {pod.ndim}")
    if any(c < 0 or c >= t for c, t in zip(coord, pod.extents)):
        raise Unreadable(f"{coord} is outside the pod")
    return coord


def _shape(text: str) -> Coord:
    try:
        return tuple(int(p) for p in text.replace(" ", "").split(","))
    except ValueError as exc:
        raise Unreadable(f"'{text}' is not a shape") from exc


# -- subcommands ------------------------------------------------------------


def cmd_shapes(args: argparse.Namespace) -> int:
    pod = _pod(_load(args.scenario)) if args.scenario else Topology.cube(args.k, args.n)
    shapes = candidate_shapes(args.chips, pod)
    if not shapes:
        print(f"REFUSED: no rectangle of {args.chips:,} chips fits a "
              f"{'x'.join(map(str, pod.extents))} pod")
        return REFUSED

    reports = [shape_report(s, pod) for s in shapes]
    print(f"{args.chips:,} chips in a {'x'.join(map(str, pod.extents))} pod: "
          f"{len(shapes)} legal shape(s)")
    print(f"  {'shape':<18}{'diam':>6}{'bisec':>8}{'wrap':>6}")
    for r in reports:
        print(f"  {'x'.join(map(str, r['shape'])):<18}{r['diameter']:>6}"
              f"{r['bisection']:>8}{r['torus_dims']:>6}")

    picks = {name: min(reports, key=key)["shape"] for name, key in OBJECTIVES.items()}
    print()
    for name in sorted(picks):
        print(f"  best by {name:<12} {'x'.join(map(str, picks[name]))}")
    if len(set(picks.values())) == 1:
        print("  the objectives agree here")
    else:
        print("  the objectives DISAGREE: the shape you get depends on what you asked for")
    return OK


def cmd_pack(args: argparse.Namespace) -> int:
    doc = _load(args.scenario)
    fabric, owners = _fabric(doc)
    demand = _requests(doc)
    refused: List[str] = []
    for request in demand:
        try:
            fabric.place(request, objective=args.objective)
            if request.tenant:
                owners[request.job_id] = request.tenant
        except NoPlacement as exc:
            refused.append(str(exc))
    print(fabric.report())
    if refused:
        print("\nrefused:")
        for line in refused:
            print(f"  {line}")
        return REFUSED
    return OK


def cmd_cordon(args: argparse.Namespace) -> int:
    if args.scenario:
        doc = _load(args.scenario)
        fabric, _ = _fabric(doc)
        pod = fabric.pod
        failed = [_coord(c, pod) for c in args.failed]
        impact = cordon_impact(fabric.allocations, failed)
        print(f"{len(failed)} failed chip(s):")
        print(impact.explain())
        print(f"  total {impact.total_chips_lost:,} chips lost")
        return REFUSED if impact.destroyed else OK

    shape = _shape(args.shape)
    rect = SliceRect((0,) * len(shape), shape)
    ex = exposure(rect)
    worst, cost = worst_position(rect)
    print(f"slice {rect.canonical()} --- {rect.chips:,} chips")
    print(f"  one chip fails: best {ex['best']:,} lost "
          f"({ex['best_fraction'] * 100:.1f}%), "
          f"median {ex['median']:,}, worst {ex['worst']:,} "
          f"({ex['worst_fraction'] * 100:.1f}%)")
    print(f"  worst chip is {worst}, costing {cost:,}")
    print(f"  spread {ex['spread']:.0f}x --- where the chip fails matters "
          f"{ex['spread']:.0f} times more than that it failed")
    return OK


def cmd_isolate(args: argparse.Namespace) -> int:
    doc = _load(args.scenario)
    pod = _pod(doc)
    domains = _domains(doc)
    demand = _requests(doc)
    policy = IsolationPolicy(
        dedicated_domains=not args.allow_sharing, domain_gap=args.gap)

    blocked = [(r.job_id, c) for r in demand for c in conflicts(r, pod, domains)]
    for job_id, reason in blocked:
        print(f"CONTRADICTION {job_id}: {reason}")
    if blocked:
        print()

    cost = isolation_cost(pod, demand, domains, policy)
    print(f"{domains.label} = axis {domains.axis} / {domains.width} chip(s), "
          f"{domains.count(pod)} of them")
    print(cost.explain())
    return REFUSED if cost.refused or blocked else OK


def cmd_reconstitute(args: argparse.Namespace) -> int:
    doc = _load(args.scenario)
    fabric, _ = _fabric(doc)
    failed = _coord(args.failed, fabric.pod)
    if args.job not in fabric.allocations:
        raise Unreadable(f"no slice named {args.job}")
    policy = AutonomyPolicy(
        max_self_loss_fraction=args.max_loss,
        allow_reshard=args.allow_reshard,
        allow_eviction=not args.no_eviction,
    )
    result = reconstitution_plan(fabric, args.job, failed, policy=policy)
    print(result.explain())
    return OK if result.verdict == "ACT" else REFUSED


def cmd_example(args: argparse.Namespace) -> int:
    doc = dict(REFERENCE)
    pod = _pod(doc)
    fabric = Fabric(pod)
    owners: Dict[str, str] = {}
    for request in _requests(doc):
        fabric.place(request)
        owners[request.job_id] = request.tenant
    print(fabric.report())

    print("\n-- what one chip costs, by where it is --")
    rect = fabric.allocations["pretrain-7"]
    for label, coord in (("a face", rect.origin),
                         ("the centre", tuple(o + e // 2 for o, e
                                              in zip(rect.origin, rect.extent)))):
        option = cheapest_shrink(rect, coord)
        print(f"  {label:<12} {coord} -> lose {option.chips_lost:,} chips "
              f"({option.chips_lost / rect.chips * 100:.0f}% of pretrain-7)")

    print("\n-- and who is allowed to fix it --")
    centre = tuple(o + e // 2 for o, e in zip(rect.origin, rect.extent))
    print(reconstitution_plan(fabric, "pretrain-7", centre).explain())
    return OK


# -- entry point ------------------------------------------------------------


def _version() -> str:
    from . import __version__

    return __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="slicepacker",
        description="What a torus pod can actually still admit.")
    parser.add_argument("--version", action="version",
                        version=f"slice-packer-torus {_version()}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("shapes", help="legal shapes for a job, and which objective picks which")
    p.add_argument("chips", type=int)
    p.add_argument("-k", type=int, default=16, help="pod extent per dimension")
    p.add_argument("-n", type=int, default=3, help="pod dimensions")
    p.add_argument("--scenario", help="read the pod from a scenario file instead")
    p.set_defaults(func=cmd_shapes)

    p = sub.add_parser("pack", help="place a demand and report what is left")
    p.add_argument("scenario")
    p.add_argument("--objective", choices=sorted(OBJECTIVES), default="diameter")
    p.set_defaults(func=cmd_pack)

    p = sub.add_parser("cordon", help="what a chip failure costs")
    p.add_argument("--shape", help="a slice shape, e.g. 16,16,16")
    p.add_argument("--scenario", help="a scenario file with allocations")
    p.add_argument("--failed", action="append", default=[],
                   help="a failed coordinate, e.g. 4,8,8 (repeatable)")
    p.set_defaults(func=cmd_cordon)

    p = sub.add_parser("isolate", help="what blast-domain isolation costs")
    p.add_argument("scenario")
    p.add_argument("--gap", type=int, default=0, help="domains to keep empty between tenants")
    p.add_argument("--allow-sharing", action="store_true")
    p.set_defaults(func=cmd_isolate)

    p = sub.add_parser("reconstitute", help="what to do after a failure, and who decides")
    p.add_argument("scenario")
    p.add_argument("job")
    p.add_argument("failed", help="the failed coordinate, e.g. 4,8,8")
    p.add_argument("--max-loss", type=float, default=0.25)
    p.add_argument("--allow-reshard", action="store_true")
    p.add_argument("--no-eviction", action="store_true")
    p.set_defaults(func=cmd_reconstitute)

    p = sub.add_parser("example", help="the reference scenario, end to end")
    p.set_defaults(func=cmd_example)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "command", None) == "cordon" and not (args.shape or args.scenario):
        print("UNREADABLE: cordon needs either --shape or --scenario", file=sys.stderr)
        return UNREADABLE
    try:
        return args.func(args)
    except Unreadable as exc:
        print(f"UNREADABLE: {exc}", file=sys.stderr)
        return UNREADABLE
    except (NoPlacement, KeyError, ValueError) as exc:
        print(f"UNREADABLE: {exc}", file=sys.stderr)
        return UNREADABLE


if __name__ == "__main__":
    sys.exit(main())
