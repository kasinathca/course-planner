# Exact local constraint solver and ranking

## Input

A *scenario* with required subjects, optional subjects and course priority tiers; credit minimum/target/maximum, pinned options, forbidden options, existing occupied periods, accepted faculty, programme compliance, calendar, and soft ranking weights.

## Correct search space

Stage 1 enumerates feasible **course selections** satisfying categories/credits and must-takes; stage 2 enumerates complete **registration options** (including all required components) for each course. A scenario that requires all listed courses skips optional-set enumeration. Do not count missing subjects as valid completions. Missing offerings/slots are explicit warnings or hard failures (strict mode).

## Algorithm

- Build each course's allowed registration options once: a struct with component rows, precomputed period bitset, credit count, faculty preference, normalized display fields and local metrics.
- Remove invalid options; use AC-style pairwise incompatibility bitsets if affordable; sort dynamic variable order by **minimum remaining values (MRV)** and conflict degree to prune.
- Search depth-first with branch-and-bound for rank; maintain occupied bitset and category credits; upper-bound achievable course-priority score and lower-bound workload to prune.
- For exact counts, use memoized DP keyed by assigned/unassigned courses, mask, remaining credit/category constraints and policy version where state space permits. When too large, use deterministic depth-first counting with cancellation, not speculative counts.
- For top-K, keep a bounded min-heap of size K, emit batches and a solution-count status. Avoid storing all timetables. Never embed a multi-megabyte index into an HTML file for each import.
- Optional OR-Tools CP-SAT backend is acceptable behind adapter if bundled completely offline; its feasibility results must match an independent small brute-force reference implementation. Prefer simple native bitset search for first version.
- Cache precomputed options, masks and results keyed by a SHA-256 of calendar+offering+scenario rules. Any change in source, preference, semester or pinned sections invalidates dependent caches.
- Cooperative cancellation via worker status flag; UI never freezes.

## Ranking policy: valid first, priorities matter

Proposed **lexicographic tiers** rather than one opaque score:

1. Hard validity and all must-take courses (required, not merely scoring).
2. Maximize inclusion of high-priority optional courses, ordered by tier/priority (may use weights *within* a tier).
3. Maximize earned **needed** category progress and credit target closeness, respecting permitted excess.
4. Minimize lab sessions/week (default high preference); then lab minutes/week.
5. Minimize days on campus and occupied span; then gaps, unwanted late hours.
6. Maximize faculty preference/availability.
7. Deterministic tie break by sorted course IDs + normalized section IDs.

Expose policy editor to reorder *soft* groups without changing hard constraints. Presets `Minimum Labs`, `Fewer Campus Days`, `Morning Theory`, `Max Credits`, `Priority Courses First` are editable. Prefer `Pareto` alternate gallery (low labs vs more days) to avoid hiding meaningful trade-offs.

## Results and transparency

For each candidate show included courses, credit subtotal / category progress, timetable, lab count, 5-day workload, faculty, why ranked, which lower-priority optional courses excluded. Explicitly separate feasibility count from shown top-K. Example: `Exact feasible 12,840; showing best 50` only after exact count is known; otherwise `50 results found; full count pending/not computed`.

## Why historical brute-force failed to scale

The saved validation report describes **469,908,488** exact assignment possibilities in one older scenario. Allocating one Python object or JS object per schedule would be enormous. The new engine searches/computes counts symbolically and holds only active branches and result heap. The historical count alone does not validate any new semester.

## Correctness obligations

Create independent reference enumerator for datasets with ≤5 subjects; randomized property tests compare optimized solver with reference for both feasibility sets and exact counts. Changing priority may change **ordering**, never feasibility. Changing a faculty from allowed to blocked may only remove feasible schedules; adding an allowed section may only add them. Every emitted result revalidated by separate time-overlap checker.
