# Changelog

## 1.0.0 --- 2026-09-02

First release.

### Models

- `torus` --- k-ary n-cube topology with closed-form diameter and bisection,
  checked against breadth-first search and exact bipartition enumeration, and
  the rule that a slice inherits a ring in a dimension only if it spans that
  dimension completely.
- `packing` --- placement, release, fragmentation, and the largest job still
  placeable, which is the number a capacity report should print instead of the
  free-chip count.
- `cordon` --- the cost of shrinking back to a rectangle after a chip failure,
  which depends on where the chip was.
- `embed` --- shrink in place against move, and the exact drain needed to make a
  move possible.
- `tenant` --- blast-domain isolation, its price in admitted chips, and the
  requests it cannot satisfy at any price.
- `reconstitute` --- the L0/L1 autonomy boundary and the cost of waiting for a
  person.

### Validation

- 24 registry points: 2 calibrated against published closed forms, 11 emergent,
  11 sanity, and 13 declined items printed above the results on every run.
- 19 mutation tests: 16 that delete machinery and assert the exact set of
  points that turns red, a green unmutated control, and 2 that assert the
  registry stays green because the blind spot is real.
- 87 unit tests, 22 examples pinned to their exit codes, 3 experiments that
  exit non-zero if their headline stops holding.

### Defects found and fixed while building this

- `is_free` tested every chip of a candidate rectangle, making a capacity report
  on a 16-ary 3-cube take minutes (DECISIONS D4).
- `largest_placeable` counted downward one chip at a time, repeating the same
  position scan thousands of times; the replacement built a `SliceRect` per
  candidate position and was barely better (D5).
- The validation registry mangled the name of any point that raised, because it
  stripped `point_` everywhere rather than as a prefix --- which silently renamed
  `checkpoint_preserving` to `checpreserving` in failure output. The same line
  existed in `optical-circuit-intent` and was fixed there too.

### Registry weaknesses found by the mutation tests, and closed

Two points passed while the machinery beneath them was deleted, which is the
failure mode the mutation tests exist to catch:

- **The autonomy point tested monotonicity, and all-zeros is monotone.** A
  control plane patched to never escalate produced `0/40` at every occupancy and
  the point stayed green. It now also requires the boundary to actually bite ---
  more than half of failures needing a person on a nearly full pod.
- **The isolation point tested that isolation costs something, and a policy that
  admits one tenant and refuses the rest costs a great deal.** Collapsing every
  rack into a single domain left it green. It now also requires the isolated pod
  to still admit at least two tenants, so a shutdown cannot pass as a price.

One further mutation was written badly rather than caught badly: an early
attempt to test double-counting duplicated the *caller's* input instead of
removing the model's guard, so it proved nothing and was replaced.
