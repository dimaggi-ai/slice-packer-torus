# Changelog

## 1.1.0 --- 2026-09-02

The repository gains its first measurement, and the boundary around it.

### Added

- `hazard` --- cohort death rates, age-resolved hazard (exposure clamped per
  bucket), the one-window evict-or-ride inequality, and a split-sample ranking
  evaluation, all measured on the public Titan GPU lifetime dataset
  (Ostrouchov et al., SC '20): 30,207 GPUs, 100,889 GPU-years.
- `make data` --- fetches the dataset from its canonical home and verifies a
  pinned SHA-256; the file is never vendored (DECISIONS D15). A missing file
  turns the registry's Titan points red rather than skipping them.
- `slicepacker hazard` CLI subcommand, two pinned examples, 17 unit tests.
- Five registry points: three calibrated to the SC '20 paper (headline
  exposure, cage ordering, the no-bathtub hazard curve with its mid-life
  magnitude pinned), one emergent (ranking beats a uniform pick on held-out
  chips, lift 1.84x), one sanity (the inequality flips at its threshold).
- Three measured mutation tests. One earned its point a sharper assertion:
  dropping the exposure clamp preserved every ordering and the red set was
  measured EMPTY until the mid-life magnitude was pinned.
- ASSUMPTIONS A12 (Titan's rates are Titan's), DECISIONS D15/D16, SOURCES S3,
  three new declined items.

### Changed

- Every absolute "no measurement in this repository" claim is re-scoped to the
  geometry, which remains unanchored; D13 records the split.

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
