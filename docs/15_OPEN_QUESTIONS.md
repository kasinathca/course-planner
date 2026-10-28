# Open decisions and requests for verification

Do not block Phase 0/1 on these; implement safe defaults and `needs_review`. Resolve before marking official timetables and graduation checks as verified.

| ID | Question | Safe initial handling | Priority |
| --- | --- | --- | --- |
| Q-01 | Obtain the **official VIT Vellore 2026–27 Winter theory/lab slot chart**, exact times, supplementary/virtual slots, and special slots. | `DRAFT_UNVERIFIED` calendar; no official validation badge. | Critical before solver release |
| Q-02 | Does VTOP enforce **same faculty** between ETH and ELA, an official shared section pairing, or allow different faculties? | Distinct pairing states; same-name matching only provisional, strict mode flags unknown. | Critical |
| Q-03 | Does VIT **require** opposite-shift theory/lab, or merely tends to offer it? What exceptions exist? | Preference, not hard constraint until documented. | High |
| Q-04 | Clarify `ETP` EPJ association, contact hours if any, registration behavior of `NIL` rows, and credits. | Zero *additional scheduled lab* by default; retain project component. | High |
| Q-05 | Confirm what 225 total and NC=5 represent for 2024–25 Integrated M.Tech curriculum. Does NC count toward graduation totals? | Preserve target as supplied, display accounting ambiguity. | High |
| Q-06 | Verify 27-credit semester cap: user historical validator models 27, but whether current maximum and exceptional overload are allowed must come from policy. | Editable profile with warning until officially verified. | High |
| Q-07 | Official prerequisite, slot equivalency, alternatives and course repeat policies (e.g. English alternatives, STS3022). | Import explicit rules only; do not infer missing prerequisites. | High |
| Q-08 | Should the initial localhost runtime support only Windows 11 or also macOS/Linux? | Windows 11 is priority; standards-based browser/UI code should remain portable. | Medium |
| Q-09 | Rank priorities: “more required credits” vs “fewer labs” when there is a tie in must-take course coverage; allow saved presets? | Default lexicographic as documented; editable preferences. | Medium |
| Q-10 | Can same user hold different published VTOP course categories/semester versions at once? | Separate snapshots with explicit active semester. | Medium |
| Q-11 | Is manual capture (one dropdown selection per subject) sufficient for v1, or should guided sequential navigation be permitted by the portal? | Manual first, with capture on change; no automatic POSTs. | Low |
| Q-12 | Optional integration: FFCSinator export only or a fully standalone replacement with identical features? | Export/import compatibility only. | Low |
| Q-13 | Should the app support friend/cohort scenario sharing through files (without online accounts)? | Local scenario export/import later. | Low |

Suggested additional input when ready: one screenshot or official downloadable PDF of the **current semester slot matrix** including real theory and lab times. Also useful: VTOP screenshot of a **single ETL course** showing ETH/ELA rows and any official rules about lab-faculty pairing. The supplied saved HTML already provides useful table structure.

## Phase 2 status — 2026-10-28

- Q-01 remains open. Calendar schema, import, immutable versioning, resolution and clash machinery are implemented, but no authentic Winter Semester 2026–27 Vellore chart was found in the supplied local references. The bundled example is synthetic and remains `draft_unverified`.
- A Fall Semester 2026–27 weekday grid is now available as a source-attributed `user_supplied` profile with exact theory/lab positions. It is not an official source, does not answer the Winter calendar question, and must remain semester-scoped.
- Q-02 remains open. Pairing states are persisted against exact offering-revision allocation IDs. No official pairing source was supplied, so required multi-component candidates fail closed when an explicit permitted pairing is absent.

## Phase 5 status — 2026-10-28

- Q-05 remains open. Version 0.6.0 preserves the displayed 225 units and recorded NC target of 5 while leaving NC graduation accounting `pending_classification`; the UI does not claim official graduation readiness.
- Q-06 remains open. Semester warning thresholds are configurable planning warnings, not an invented hard 27-credit policy.
- Q-07 remains open. The prerequisite and relationship engines accept explicit evidence and prevent requirement double-counting, but no missing English/ENG1902–ENG1903/GER1001 institutional rule was fabricated. STS3022 source identities remain distinct in synthetic regression coverage.
- The consolidated curriculum and five private legacy snapshots were not present in the permitted local references. Their actual 101-course catalogue and 35 completions remain pending reviewed local import.

## Phase 6 status — 2026-10-28

- Q-11 is implemented with the conservative manual-selection-first collector. Its dynamic sanitized harness passed, but the authenticated current VTOP allocation page and exact live allocation route were not available; real-page acceptance remains pending user-supervised verification.
- Q-12 is resolved as explicit import/export compatibility only. Legacy TypeScript semantics are labeled lossy, parsed without code execution and stored with `legacy-ffcsinator` provenance.
- Q-13 is implemented through strict local scenario file export/import. Imported scenarios are always independent copies and are rechecked against current local source revisions.
- Public binary distribution remains undecided pending a project-wide licence decision and runtime-bundling review. Version 0.7.0 is a verified source installation and wheel, not a signed installer.
