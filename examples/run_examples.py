#!/usr/bin/env python3
"""Run every example through the CLI and check it reaches its documented result.

The exit code is the assertion. ``1`` means refused, which is a correct answer
and the one most of these examples exist to produce; ``2`` means the input could
not be read. An example that started returning ``0`` where it used to refuse
would be a regression this catches and a reader would not.
"""

from __future__ import annotations

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "src")

OK, REFUSED, UNREADABLE = 0, 1, 2

CASES = [
    (["example"], OK, "the reference scenario, end to end"),
    (["shapes", "4096", "-k", "64", "-n", "3"], OK,
     "28 legal shapes; the three objectives disagree"),
    (["shapes", "4096", "-k", "16", "-n", "3"], OK,
     "one legal shape; the objectives cannot disagree"),
    (["shapes", "17", "-k", "16", "-n", "3"], REFUSED,
     "17 chips has no rectangle and is not rounded up"),
    (["cordon", "--shape", "16,16,16"], OK,
     "8x spread between the cheapest and dearest chip"),
    (["cordon", "--shape", "1,64,64"], OK,
     "same chip count, 32x spread"),
    (["cordon"], UNREADABLE, "nothing to work on"),
    (["pack", "pod-empty.json"], OK, "everything fits"),
    (["pack", "pod-fragmented.json"], REFUSED,
     "free chips on the floor and nowhere to put a 1,024-chip job"),
    (["pack", "pod-oversubscribed.json"], REFUSED, "more demand than pod"),
    (["pack", "pod-illegal-wrap.json"], UNREADABLE,
     "a ring of two is not a ring"),
    (["pack", "pod-not-json.txt"], UNREADABLE, "not a scenario"),
    (["pack", "/nonexistent.json"], UNREADABLE, "no such file"),
    (["isolate", "tenants-isolated.json"], REFUSED,
     "isolation refuses tenants an open pod would have taken"),
    (["isolate", "tenants-isolated.json", "--gap", "2"], REFUSED,
     "a wider gap refuses more"),
    (["isolate", "tenants-contradictory.json"], REFUSED,
     "wraparound and isolation contradict each other"),
    (["cordon", "--scenario", "failure-no-room.json", "--failed", "4,8,8"], OK,
     "one chip failure shrinks one slice"),
    (["reconstitute", "failure-room-to-move.json", "pretrain-7", "2,8,8"], OK,
     "a same-shape move exists: the control plane may act"),
    (["reconstitute", "failure-no-room.json", "pretrain-7", "4,8,8"], REFUSED,
     "every option needs a person"),
    (["reconstitute", "failure-no-room.json", "pretrain-7", "4,8,8",
      "--allow-reshard", "--max-loss", "1.0"], OK,
     "the same failure, once a reshard is permitted"),
    (["reconstitute", "failure-no-room.json", "no-such-job", "4,8,8"], UNREADABLE,
     "no slice by that name"),
    (["reconstitute", "failure-no-room.json", "pretrain-7", "99,0,0"], UNREADABLE,
     "outside the pod"),
    (["hazard", os.path.join(ROOT, "data", "titan_gc_summary_loc.csv")], OK,
     "the Titan fleet: rank for placement, ride out the eviction"),
    (["hazard", "no-such-fleet.csv"], UNREADABLE,
     "no dataset fetched --- the answer is `make data`, not a guess"),
]


def main() -> int:
    env = dict(os.environ, PYTHONPATH=SRC)
    failures = []
    for argv, expected, description in CASES:
        result = subprocess.run(
            [sys.executable, "-m", "slicepacker.cli", *argv],
            cwd=HERE, env=env, capture_output=True, text=True)
        mark = "ok " if result.returncode == expected else "BAD"
        print(f"[{mark}] exit {result.returncode} (want {expected})  "
              f"slicepacker {' '.join(argv)}")
        print(f"        {description}")
        if result.returncode != expected:
            failures.append((argv, expected, result.returncode,
                             result.stderr.strip() or result.stdout.strip()[-300:]))

    print()
    if failures:
        print(f"{len(failures)} of {len(CASES)} examples reached the wrong result:")
        for argv, want, got, output in failures:
            print(f"  {' '.join(argv)}: wanted {want}, got {got}\n    {output}")
        return 1
    print(f"all {len(CASES)} examples reached their documented result")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
