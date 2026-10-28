# Integrated degree-planning module

## Programme rules supplied

Integrated M.Tech CSE (Data Science), admission 2024–25. Curriculum summary as recorded in supplied consolidated Markdown:

| Category | Target |
| --- | ---: |
| PC | 81 |
| PE | 48 |
| UC | 61 |
| UE | 12 |
| SPE | 18 |
| BC | 0 |
| NC | 5 |
| Recorded programme total | 225 |

These are the **source-specific values**. Do not silently reinterpret NC's label/units: the consolidated document labels it `Non-Credit Course` while target column shows `5`. Keep a configurable credit-accounting policy and surface reconciliation issues.

## User experience

- All-semester matrix: semester 1..10 with rows for planned courses, completed courses and course categories.
- Top-level progress shows `Earned / Enrolled / Planned / Remaining` separately, both category and total.
- Per-semester/category ledger alongside cumulative progress and credit ceiling.
- “Next best courses” only considers prerequisites, degree gaps, repeats, course type/number of labs, and **verified current offerings**.
- Allow speculative future course placement even when offerings unknown; tag clearly `tentative` and do not generate faculty schedules without actual offering rows.
- Report required courses that are not offered, surplus category credits, overbooked term credits, mutually exclusive alternatives, missed programme targets, and workload consequences.
- Scenario branches should preserve independent plans: `min labs`, `accelerate PE`, `avoid late classes`, etc.
- End-to-end integration: select semester 6 plan -> ask to generate timetable from **semester 6** offering snapshot -> transfer back registered/locked sections.

## Migrations

Version-6 source snapshots list 101 catalog entries and 35 completed entries. `plan` maps string semester numbers to arrays containing `courseId`, `availability`, `status`, `customTitle`, `notes`. Import them in timestamp order into separate snapshots and let the user choose a main timeline. Example: `sem 9 10.json` has semester 10 empty whereas an earlier file has one planned item; do **not** merge both indiscriminately.

Maintain the distinctive `STS3022` catalog alternatives and course basket selections. Subject equivalencies (`Technical English II` vs `Advanced Technical English`), outside electives, foreign-language basket `GER1001`, extracurricular `EXC1072` and intentionally omitted syllabus files remain independently traceable.

## Course availability vs graduation progress

Offering presence is semester-local; a credit target is programme-local. A course can be completed without being offered this semester. A course can be offered but not count toward a currently needed basket if already satisfied. An elective may exceed a category target by unavoidable 1 credit; warn vs hard block per programme policy. Never count credits for both equivalent alternatives.

## Phase 5 implementation status

Version 0.6.0 implements these rules in `ffcs_studio.degree` with exact integer milli-credit arithmetic, explicit record statuses, source-backed relationship groups, a conservative prerequisite evaluator, ten-semester totals, category surplus warnings, and configurable semester warning thresholds. SQLite migration 0004 stores programme/curriculum revisions, catalogue identities, relationships, prerequisites, plan revisions, manual availability history, scenario links, and recovery decisions without changing migrations 0001–0003.

The recorded PC/PE/UC/UE/SPE/BC/NC targets are seeded as a programme-specific 2024–25 policy. NC remains `pending_classification`; it is displayed but is not silently counted as ordinary confirmed credit. The private consolidated curriculum and five historical JSON snapshots were not present in the designated references during Phase 5, so the real 101-course/35-completion migration is not claimed. The reviewed canonical and legacy import paths are exercised with conspicuously synthetic fixtures instead.
