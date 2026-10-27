# Slot calendar, clashes and component pairing

## Correct representation

Maintain a campus+semester versioned **mapping of atomic slot code → 1 or more real weekly day/minute intervals**. Convert `B1+TB1` to a union of *B1* and *TB1* intervals; convert `L1+L2+L15+L16` to four L-unit periods, with adjacent units potentially displayed as two lab blocks. Do not infer daily occurrence from row/column coordinates in FFCSinator's CSS grid. During integration import slot grids from the legacy code **only as candidate mappings**, cross-checked with current VTOP timetable.

Each period: `day_index: 0..6`, `start_minute` inclusive, `end_minute` exclusive (from midnight, e.g. 08:00=480); add `kind`, `shift`, `timezone='Asia/Kolkata'`, `source`, `verified`. `slot_code` may represent repeated theory meetings and must support variable weeks/campus calendar overrides.

## Clash definition

Intervals conflict when `dayA==dayB && startA < endB && startB < endA`. Adjacent end/start boundaries **do not** collide. Verify slot mapping completeness before marking plan valid. Unknown slot(s) make the candidate `unverified` and unschedulable in strict mode.

For performance precompute a calendar-specific occupancy bitset over atomic disjoint periods; use integer bitwise `&` for search, after validating actual minute intervals. If the user changes calendar profile, invalidate these masks.

## Lab calculation / attendance burden

The user wants less on-campus time. Compute and expose separately:

- `lab_sessions_per_week`: number of distinct lab sessions, merging adjacent L units within the **same registered lab block**, not total number of L tokens / 2 without verification.
- `lab_minutes_per_week`, `theory_minutes_per_week`, `total_campus_minutes`, `days_on_campus`, `first_arrival`, `last_departure`, `interclass_gap_minutes`, and max-late-class indicator.
- `project_component_count`, `estimated_project_effort = unknown by default`; ETP does not automatically equal zero total work.
- Faculty and venue for each visible session.

## Pair construction

Generate **registration options** before global timetable search:

1. TH: each TH section is one option.
2. ETL: theory section × only **verified/allowed** ELA sections, not a naive cross-product. If faculty-link policy `same_name` is explicitly selected and identities match, label provisional if no institutional linkage.
3. ETP: one ETH section + matching EPJ record if present. If EPJ repeats theory slot, count theory time **once**. No automatic lab-block assignment.
4. LO, ELJ and special types: per configurable per-course component template; when template incomplete block candidate with review prompt.
5. Reject candidates with internal conflicts and missing essential components.

## Test scenarios

- `A1+TA1` vs `A1` must collide.
- `L1+L2` vs a theory section occupying Mon morning L1 or L2 times must collide.
- `L1+L2+L15+L16` must occupy **both** actual lab blocks; do not truncate after first pair.
- `C1` and `C2` must map to their actual slots, not automatically treated as simultaneous.
- `ETH:A1+TA1` plus `EPJ:A1+TA1, NIL` should create one theory occupancy, zero additional lab blocks.
- A valid ETL course must include its required lab component.
- Different subjects with identical period but different rooms still clash.
- `TAA1`, `TCC1`, `TBB2`, `TDD2` must be explicitly in calendar; no blanket T-prefix assumptions.

## Time source warning

Third-party sites currently show Vellore L1–L30 morning and L31–L60 afternoon; these are useful clues, **not** a substitute for the current official VTOP semester slot timetable. Some third-party minute boundaries differ. Ship with a `DRAFT_UNVERIFIED` profile that cannot silently certify a schedule until checked against official slot layout.
