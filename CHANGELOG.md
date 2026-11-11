# Changelog

## Unreleased

A second fabric: cubes joined by optical circuit switches, compared with the
static torus on matched seeds. Nothing existing changes.

### Added

- `ocs` --- a pod of cubes (default 4x4x4) stitched by optical circuit
  switches: super-slices of whole cubes, sub-slices inside one cube, a port
  limit that splits the pod into domains, a shape cap, and borrow or reserve
  spare-cube policies with swap, re-stitch and cordon recovery. A ring exists
  only where a closing circuit is configured; the chip graph is built from the
  circuit list and its diameter checked against the closed forms.
- `experiments/ocs/compare.py` --- the three static experiments rerun for both
  fabrics on matched seeds, plus the cases where cubes do not help: sub-cube
  jobs, sizes that are not whole cubes, shape caps, port limits and spare cost.
  Exits 1 if any of its headlines stops holding (13 after the assurance fixes).
- `validation/validate_ocs.py` --- a separate registry: 18 points (2
  calibrated to Jouppi et al., ISCA 2023 and Dally 1990, 9 emergent, 7 sanity)
  and 13 declined items, including that Google's 5x and 4.5x figures are vendor
  claims and not inputs.
- `tests/test_ocs.py` --- 30 tests: 18 on behaviour and 12 measured mutations.
  One asserts a blind
  spot: no point measures sub-cube utilisation. The adjacency mutation first
  measured an empty red set; the gap point now releases a matched third of
  jobs before measuring.
- `docs/ocs-cubes.md` and an additive README section.
- `make ocs-smoke` (the comparison with reduced trials, ~45 s) and
  `make experiments-ocs` (the full comparison, ~4 min).

### Changed

- `make validate` also runs the OCS registry; `make smoke-test` also runs
  `ocs-smoke`. CI gains two steps in the existing style: the OCS registry and
  the reduced-trial comparison. No new actions or network destinations.
- `evidence.json` rebinds README.md and docs/ocs-cubes.md, whose text
  changed for these targets.
- README finding 3, `docs/the-models.md` section 3, the paper's abstract and
  conclusion, and DECISIONS D2 now say the failure-cost figures (256--2,048
  chips by location for `16x16x16`) assume a face-pull-only shrink with no
  seam crossing (ASSUMPTIONS A2). A slice that spans a whole ring could
  instead re-form through the wraparound for 256 chips anywhere, at the cost
  of one ring (`slicepacker.seam`, `docs/ocs-cubes.md` section 2). This edits
  existing README text. No code, number or output changes.

### Fixed (assurance findings on the OCS mode, 2026-11-09)

- **A stronger static baseline (A1).** The static cordon only pulls a face
  inward and never re-forms a slab across the seam (ASSUMPTIONS A2), so it
  charged a centre failure 2,048 chips. New opt-in `slicepacker.seam`:
  a seam-crossing shrink (drop the failed plane, keep the rest through the
  seam; costs one plane and that axis's ring) and `SeamFabric`, which places
  across the seam. `cordon.py` and `Fabric` are unchanged, and so is every
  existing output. The OCS comparison reports both baselines. With
  seam-crossing on both fabrics, one failure costs 256 chips everywhere on
  each, so the headline "without a spare, cubes halve the worst case" holds
  only against the no-seam baseline and is restated that way.
- **The spare case runs on more hardware (A2).** A 65th cube and 136 rather
  than 128 ports per switch. Declined item 10 and the tables say so.
- **Reserved spares are held per domain (A3).** Before, reserve mode held the
  last N cubes of the pod, all in the last domain. Reserving more spares than a
  domain holds is now an error.
- **`copy()` keeps a used-up spare pool used up (A4).** The sentinel is now
  `None`; an empty list meant "fill in again".
- **Reached occupancy is reported beside each target (A5).** Off-cube rows are
  shown with what was admitted, and no benefit is claimed from them.
- **The OCS port check looks at face positions (A8).** It waived the check for
  any self-loop on a shared cube; it now checks the positions each loop uses.
- `tests/test_ocs_assurance.py` (19 tests, each written and run failing before
  its fix) and three new mutations: pod-wide spares, a copy that refills the
  pool, and no seam-crossing. The registry is 18 points (2 calibrated, 9
  emergent, 7 sanity) and 11 declined items at that point; `compare.py` has 13
  headlines.

### Fixed (CTO review of PR #1, 2026-11-10)

- **Reserved spares are pinned to their domain by a test.** A swap that took
  a spare from another domain passed every test. Two tests in
  `tests/test_ocs_assurance.py` now fail on it.
- **`recover()` and `apply_swap()` refuse a sub-cube job by name.** Both
  raised `KeyError`. They now raise `ValueError` before any state changes. A
  sub-cube slice has no failure path in this model (declined item 13).
- **Only the 4x4x4 cube is tested, and the registry says so** (declined item
  12). The OCS registry now prints 13 declined items.
- The clamp of the shape cap to the domain size in `cube_shapes` changes no
  answer through any caller in the model. It stays as a defensive line, with
  a comment and a direct-call test.
- `tests/test_ocs_assurance.py` holds 25 tests (6 added). `make test`
  collects 182: 127 on the static model and 55 on the OCS mode.
- Counts and ranges corrected in this file, `README.md`, `paper/paper.md`,
  `DECISIONS.md` and `docs/ocs-cubes.md`. The paper's finding 3 no longer
  says the worst case is half the slice for every shape: a shape with only
  odd sides loses more (18 of 27 chips for `3x3x3`). The 6 to 50% range in
  `README.md`, the paper and `docs/ocs-cubes.md` is now stated for the
  `16x16x16` slice it was measured on. `docs/ocs-cubes.md`
  lists four no-benefit cases beside its first results table.
- `evidence.json` re-binds `src/slicepacker/ocs.py`,
  `validation/validate_ocs.py`, `README.md` and `docs/ocs-cubes.md`, the four
  bound files this review changed. No other entry changes.

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
