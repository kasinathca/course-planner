# Test strategy, reference oracles and release gates

## Source regression fixtures

- Three sanitized saved-VTOP states: no subject, theory-only MDI3002, theory+lab CSI3002. Preserve header strings, multi-slot combinations, and original row order.
- Historic winter workbook 27 courses and 181 allocation rows: **expected historic counts from previous conversion**, validate actual imported rows and per-category totals; do not assume this corresponds to the current live VTOP.
- `data.zip` sample keys `CSI3001L`, `CSI3001P`; `CSI3007L`, `CSI3007P` with four L units; `CSI3013L` including `NIL` EPJ rows.
- Five degree JSON variants, including sem10 capstone planned then removed, and deliberate STS3022 alternatives.
- Historical validation counts from standalone file: 991,428 valid subject-set records and 469,908,488 exact assignments are optional **legacy parity targets** after exact old input/policies can be recreated, not primary pass/fail for new engine.

## Required tests

1. **Raw capture:** selected category/course verified before and after parsing; source table headers exact; no auth field serialized; duplicate fragment IDs tolerated; stale course transition not recorded.
2. **Data integrity:** preservation of records as source; full component count; invalid rows reported; same file import idempotent; changed semester never overwrites old snapshot; CSV round trip including commas in faculty names.
3. **Curriculum:** year/batch-specific credits, category targets, repeated alternative code, no double-counting equivalencies, earned vs planned vs registered, warning/override for one-credit excess where permitted.
4. **Component pairing:** ETL requires ETH+ELA; project EPJ retained but no phantom lab; one faculty with two available labs produces separate choices; course with missing ELA cannot be marked valid in strict ETL mode.
5. **Time:** same/day interval overlap, equal boundaries, split and repeated theory slots, four-unit lab, virtual/meeting-only slots, morning/evening shift; unknown slot fails strict validation.
6. **Search:** exact count and top-K equal to reference for small exhaustive examples; all solutions revalidated independently; ranking cannot turn impossible into valid.
7. **Incremental:** pinning an option can only shrink feasible set; allowing more options can only enlarge; replacing selected course triggers correct cache invalidation.
8. **Reliability:** invalid/corrupt import rollback; interrupted shutdown while saving; known DB migration; Windows path with spaces; duplicate course title different code; case/whitespace faculty normalization.
9. **Accessibility and UX:** keyboard complete workflow, search responsiveness, smallest supported viewport, alt explanations, high contrast, stable controls and cancellation.
10. **Performance:** medium and large synthetic fixture datasets; benchmark time to first 20 results, exact-count completion (separately), peak memory and cancel latency; forbid unbounded solution arrays.

## Acceptance milestones

| Gate | Required evidence |
| --- | --- |
| G1 Import | Saved VTOP sample and schema-v1 JSON round-trip with zero silent record loss; unknown types flagged |
| G2 Domain | Slot conflict unit tests and pairing fixtures pass, including ETP and four-L-slot ETL |
| G3 Solver | Deterministic reference equivalence on random small cases and optimized top-K; strict valid-solution validator |
| G4 UX | Simple screen workflow usable at 1280×720, state persistence and detailed option explanation |
| G5 Degree | Five historical JSON snapshots import; no silent cross-snapshot union or completed/planned conflation |
| G6 Live mode | Manual full-slot and pinned-registration recovery without external requests |
| G7 Runtime | Clean offline local-site startup with Python prerequisites, no Node, no CDN, `127.0.0.1` binding, backup/export and documented shutdown |

A gate fails on *any* silent data loss, invented class timing, falsely paired section, invalid recommended schedule, non-cancellable runaway search, or unredacted portal credentials in export.

## Benchmark reporting format

Record OS, CPU, Python version, fixture hash, number of offered courses, section options, max credits, exact feasible solution count if finished, 95th percentile latency to first top-20, memory peak, and cancellation latency. Avoid claiming “milliseconds” or “millions handled instantly” absent real measurements.
