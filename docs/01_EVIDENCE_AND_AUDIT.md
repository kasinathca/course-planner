# Source audit and provenance

This table distinguishes observed facts from assumptions. Source attachments were reviewed for structure, but exhaustive line-by-line correctness of all historical planner logic was **not** certified.

| Source | Observations | Migration action / limitation |
| --- | --- | --- |
| `vtop html.zip` | Three saved VTOP pages: before selection, and two with selected subjects. `#curriculumCategory` values `PC PE UC UE SPE BC NC`; dependent `#courseId`; response injection into `#courseListFragement` and `#courseDetailFragement`; four-column allocation table (`Slot Detail`, `Venue`, `Faculty`, `Course Type`). | Capture **rendered** tables after selection; user script must not persist complete HTML as it includes authenticated-page data. Both fragments were observed with duplicate same-value IDs in nested elements; parsers cannot assume unique IDs. |
| `VIT_Winter_2026-27_Course_Allocation_By_Category.xlsx` (prior conversion) | Existing 27-course / 181-allocation-row winter snapshot, grouped PC=3, PE=15, UC=3, SPE=6 in the earlier conversion. | Historical import regression reference, not evergreen 2027 data. A record may offer ETH and ELA rows separately. |
| `data.zip` | FFCSinator TypeScript school-specific tables (for example `MID_5YEAR/ProgrammeCore.ts`, `ProgrammeElective.ts`) map keys such as `CSI3001L - Cloud Computing Methodologies` and `CSI3001P - Cloud Computing Methodologies` to `{slot, venue, faculty}` records. | Import adapter must map `L` theory and `P` practical **in this source dialect**, not use naive code suffix rules for all institutional course codes. Data was semester-specific and cannot be reused as current offerings. |
| `my ffcsinator with node modules folder.zip` | Next.js 15 / React 19 project, `src/lib/slots.ts` for slot-grid/clash definitions, `src/lib/utils.ts` `generateTT`, `src/components/cards/FacultySelector.tsx`, and TypeScript course types. | Reference-only; use a new Python application. Exclude `.next` and `node_modules` from future ZIPs. `generateTT` expands combinations into an array, a scalability risk when choices multiply. Verify time rules independently. |
| GitHub `CodeChefVIT/ffcs` | Upstream repository default branch `prod`, code publicly available under MIT; README documents priority-based timetables, faculty/slot choices and Next.js/MongoDB. | Keep copyright/license attribution if reusing code. Import format compatibility does not require copying its UI. Source: https://github.com/CodeChefVIT/ffcs |
| `FFCS_Friends_ADVT_Global_Smart_Planner.html`, `_Index.js`, `_Validation.txt` | A local planner with indexed schedule search and extra guided flows. Validation text reports **991,428** clash-free subject-set records and **469,908,488** exact faculty schedules over D1/D2 STS scenarios. | These are **historical reported outputs**, not current winter results or a fresh independent proof. Treat as regression benchmarks once source assumptions, historical inputs and uniqueness semantics are reconstructed. Never eagerly materialize that many assignments. |
| `FFCS HELPER KASI.html` | Standalone FFCS support tool: faculty/section selection, registration state, recovery and replacement workflow. | Rebuild workflows with separated domain logic rather than copying inline DOM code. |
| `COURSE PLANNER MAIN.html` | Degree planning, category progress, semester cards, imports, course catalog, credit warnings, offerings. | Migrate as degree-planning module with a consistent course schema. |
| `5th sem.json`, `sem 6 also.json`, `sem 7.json`, `sem8.json`, `sem 9 10.json` | All follow version `6`, with `catalog`, `completed`, `plan`, `settings`, `offerings`, `updatedAt`. Each catalog has **101 entries** and **35 completed records** in the inspected snapshots. Planner rows use `courseId`, **not** `code`. `STS3022` deliberately appears as alternatives. | Preserve separate dated snapshots, import and diff; never union planned entries from different snapshots as if simultaneous. Some planned rows are provisional or later removed. |
| `MTech_CSE_Data_Science_Curriculum_2024-2025_Corrected_MDI3004_Complete.md` | Category targets: PC81, PE48, UC61, UE12, SPE18, BC0, NC5, total 225 (published in user's curriculum consolidation). Notes intentional omissions, alternative STS course, ENG constraints, MDI4008 title and detailed MDI3004 scope. | Treat as program-specific baseline from supplied curriculum; maintain editable versioned rules. NC may be titled “Non-Credit” while carrying a target of 5; avoid conflating all totals until the credit semantics are verified. |
| `SHEPHERD_LICENSE_AGPL-3.0.md` | Supplied Shepherd.js dual-license information includes AGPL-3.0 and commercial conditions. | Avoid bundling Shepherd.js. Use small accessible, self-authored browser help or a clearly licensed alternative. If code is ever reused, review licensing independently. |

## Evidence hierarchy

1. Explicit campus-and-semester official academic documentation or actual VTOP course allocations.
2. User-provided curriculum applicable to the admission batch.
3. User-provided saved VTOP snapshot / prior correct FFCS allocations.
4. Source code from legacy projects as **implementation evidence**, not university policy.
5. Third-party FFCS websites as independent clues only.

## Where VTOP differs from course catalog

VTOP allocation rows contain raw codes, slots, venue, faculty and row type (TH/ETH/ELA/EPJ/SS). The **curriculum catalog** contains L/T/P/J and academic type (TH/ETL/ETP etc.). These are different dimensions; one cannot infer ETP only from a `NIL` EPJ record without matching and verifying the academic catalog.

## Source locations

- `examples/vtop_selected_theory_only.json` and `examples/vtop_selected_eth_ela.json` are **redacted normalized excerpts** derived from saved HTML with course identities matched to the supplied PDF (no login ID, CSRF or portal scripts). Their `captured_at=2000-01-01` is a **synthetic fixture placeholder**, not the true capture time.
- The previous winter workbook can be supplied **separately** as an optional old-semester cross-check; it is **not included** because the original has a student registration identifier in worksheet metadata/cells.
- Other inputs are intentionally **not embedded** in this documentation ZIP because some contain portal HTML with session-related values. Supply the original archives to Codex only in a separate private local working directory if exact migration is needed.
