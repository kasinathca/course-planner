# Phase 4 browser workspace engineering report

Phase 4 turns the Phase 3 solver controls into a persistent, responsive local planning workspace. The release version is 0.5.0 and the SQLite schema version is 3. All runtime assets remain local; there is no Node.js, CDN, cloud service, external API, or hosted database.

## UI architecture and navigation

The application has five persistent destinations: Overview, Courses & Data, Timetable Planner, Degree Planner, and Scenarios. Degree Planner is explicitly labeled as a Phase 5 feature and reports no fabricated progress. The page shell is server-rendered HTML; small vanilla-JavaScript ES modules own API access, navigation, import browsing, planner state, timetable rendering, and scenario management. A single bounded in-memory `WorkspaceState` provides unsaved-change tracking and 60-step undo/redo for scenario-document edits. Imported source data is never changed by undo.

At desktop width, Timetable Planner is a three-zone workspace: course roles and evidence on the left, the selected weekly timetable in the center, and bounded ranked alternatives on the right. The zones collapse to one column below 820 CSS pixels. At 390 pixels the final measured document had no horizontal overflow; navigation scrolls independently. The 1280-pixel measurement retained three columns. Advanced constraints and evidence permissions remain in a progressive-disclosure footer.

Courses and faculty are selected from actual SQLite offerings, revisions, allocations, and derived registration candidates. Users never type allocation IDs. Curriculum type and credit values have independent provenance controls. Required, preferred, and excluded roles are separate from hard allocation/faculty locks and soft ranking preferences.

## Timetable rendering and result lifecycle

The weekly renderer consumes only exact solver meeting intervals. Seven day lanes support weekends, multiple meetings, exact minute offsets, exact duration heights, empty weekdays, long labels, and keyboard-focusable meeting buttons. A parallel semantic table exposes day, exact time and duration, course, component, faculty, venue, and slot. Colors are supplementary; every block has a descriptive accessible name. Browser acceptance rendered three 50-minute meetings with `height: 50px` and matching table rows.

Search and exact count retain independent backend state. A monotonically increasing browser poll generation prevents an obsolete poll from overwriting a newer job. Result pages are fetched in bounded pages of 20 while their global rank remains stable; local subset sorting is labeled separately. Users can compare two or three generated results, inspect differing courses, sections, credits, labs, days, contact time, gaps, daily spans, and assumptions, then transfer selected assignments into reviewed hard locks and regenerate. Historical saved snapshots can also be compared without reconstructing assignments from current source rows.

## Scenario persistence, revisions, and compatibility

Additive migration `0003_saved_scenarios.sql` creates `saved_scenarios`, `scenario_revisions`, and `saved_timetable_results` plus lookup indexes. Migrations 0001 and 0002 are unchanged. Upgrading a version-2 database creates a consistent backup first, preserves prior records and `app_state`, advances `PRAGMA user_version` to 3, and passes `PRAGMA foreign_key_check`.

Every saved scenario has a validated document schema version, current revision, status, campus/semester/calendar lookup fields, timestamps, and immutable revision rows containing canonical JSON plus source references. Create, rename/update, duplicate, list, open, restore-as-new-revision, archive, unarchive, and confirmed permanent deletion are supported. Incomplete structurally valid drafts can be saved without a solver job. Updates, restores, archives, and deletion use expected revision values; a stale writer receives HTTP 409 rather than overwriting newer work.

Scenario compatibility checks preserve offering revision IDs, allocation IDs, and calendar IDs. Missing, superseded, inactive, or mismatched references are explained and make a scenario draft or stale as appropriate; they are never silently relinked. Solver validation independently produces a scenario fingerprint. Revision identity and fingerprint are both retained because they answer different audit questions.

## Saved timetable semantics and exports

A completed job result can be named and saved only when its solver fingerprint matches the current saved scenario revision. The immutable snapshot contains the exact assignments and intervals, solver/result identity, scenario revision, calendar, offering/revision/allocation references, metrics, explanation, verification status, assumptions, and timestamp. Multiple snapshots and one preferred snapshot are supported. They survive process restarts and are labeled as historical records with a current compatibility report. A missing in-memory job cannot fabricate a snapshot.

Offline exports include versioned scenario JSON, immutable timetable JSON, UTF-8 BOM CSV with standards-compliant quoting and spreadsheet-formula neutralization, generated-result JSON/CSV, and an A4 landscape browser print stylesheet. Scenario JSON import is deferred: exports are reviewed and portable, but Phase 4 does not silently create or overwrite a scenario from an uploaded document.

## Accessibility and security

The interface uses landmarks, one visible H1 per destination, explicit form labels, live status regions, native dialogs with `aria-labelledby`, focus-visible styles, 40-pixel minimum controls, semantic tables, native checkboxes/selects, and a keyboard skip link. The router preserves the active destination when `#main-content` receives focus. Meeting blocks are buttons, not pointer-only canvas objects. Strict and exploratory evidence labels remain visible in UI, saved documents, snapshots, and exports.

Existing loopback binding, Host and Origin enforcement, CSRF checks, request-size limits, structured errors, and CSP remain active. Browser modules create text with `textContent`; imported strings are not evaluated. Scenario/result storage stays under the configured application data directory. No private VTOP page, credentials, personal academic record, or local database is part of the repository.

## Verification and measurements

The final automated suite has 130 tests. It covers the Phase 0–3 regressions plus v2-to-v3 migration/backup, draft preservation, scenario create/update/rename/duplicate/archive/restore/delete/restart, revision conflict, invalid payloads, reference compatibility, real completed-job snapshots, multiple snapshots, preferred selection, missing-job rejection, restart recovery, export correctness, and CSV formula neutralization.

Final quality gates:

- `python -m pytest`: 130 passed.
- `python -m ruff check .`: passed.
- `python -m ruff format --check .`: passed.
- strict `python -m mypy src`: passed.
- `python -m pip check`: no broken requirements.

Real localhost browser verification used only public/sanitized data in an isolated configured data directory. It completed import validate/preview/commit, calendar validate/preview/commit, course selection, explicit exploratory evidence, exhaustive generation, exact-minute grid selection, three-result comparison, lock/regenerate, scenario save, server restart, scenario reopen, two immutable result saves, preferred selection, JSON/CSV downloads, mobile/tablet/desktop layout checks, skip navigation, undo/redo, and console inspection. No console warning or error was present. Server shutdown terminates the process-backed job manager.

Observed browser interaction measurements on the small sanitized acceptance scenario (including automation round-trip overhead, so not a benchmark guarantee) were:

| Interaction | Observed time |
|---|---:|
| Open saved scenario and load catalog | 210 ms |
| Exhaustive five-result generation | 741 ms |
| Switch rendered result | 285–336 ms |
| Filter the loaded course list | 28 ms |
| Lock and regenerate one retained result | 606 ms |
| Save scenario revision | 294 ms |

The Phase 3 public eight-course benchmark and exact-count tests remain unchanged; Phase 4 does not move enumeration into the browser or retain an unbounded result set.

## Known limitations and Phase 5 readiness

- The Fall calendar remains user-supplied rather than independently verified, so it requires explicit exploratory authorization.
- Browser print CSS and the print button are implemented; automated control of the operating-system print preview is environment-dependent, so final PDF destination selection remains a user action.
- Scenario JSON import/reconciliation is not implemented. JSON export is versioned and complete, and import must later use validate/preview/create semantics without overwrite.
- Saved-timetable comparison is scoped to snapshots of the currently open scenario. Scenario documents themselves expose revision/history differences but do not yet have a field-by-field cross-scenario diff screen.
- Degree planning and curriculum-category progress remain Phase 5 work.

Phase 5 can build on stable scenario revisions, source identities, immutable result snapshots, and the five-destination shell without changing Phase 3 feasibility rules.
