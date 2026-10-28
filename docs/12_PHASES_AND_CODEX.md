# Development phases and Codex execution contract (local browser edition)

## Phase 0 — repository, models, validation and localhost proof

- Audit repository and all supplied documentation; ignore private portal HTML, account details and legacy node_modules.
- Set up Python project with CLI, typed canonical models, schema-v1 JSON validator and sanitized fixtures/tests.
- Create **minimal but functioning FastAPI app** with `GET /health`, `GET /` and locally served static assets. No full planner UI yet: plain semantic page showing product name and runtime health is enough.
- Create `scripts/start.ps1` to launch on `127.0.0.1:8765`; document `python -m ffcs_studio serve` startup and shutdown.
- Test actual HTTP response, no CDN or remote runtime calls, no secret files, one-click Windows startup where runnable. Add an issues/unknown-rules register.
- **Deliverable**: verified local website startup + validated fixture CLI + test results; stop before Phase 1.

## Phase 1 — canonical importer and SQLite

- Build JSON/CSV import, dry-run preview, SQLite schema + migrations, semester snapshot diff/commit and row-level validation reports.
- Legacy degree JSON adapter with preserved snapshot identity, curriculum import as feasible.
- Expose validated local API endpoints and a **simple functional browser import screen**. The UI must call real backend services; no mock data.
- **Deliverable**: import → preview → commit → browse real allocation rows offline in browser.

## Phase 2 — versioned calendar and component rules

- Versioned slot calendars with evidence status; component parser, interval overlap, faculty pairing rule states, ETL/ETP/TH handling. If an authentic official source is unavailable, implement the machinery with synthetic draft data and keep the official calendar question open.
- Explicit uncertain/unknown validation results; never mark unverified timetable valid.
- **Deliverable**: rule suite and issue tracking pass.

## Phase 3 — solver and ranking

- Tiny brute-force reference, optimized lazy search/bitset/MRV/pruning, top-K and accurate counting separately.
- Deterministic priority ranking, explanations, `cancel` and progress jobs exposed through localhost.
- **Deliverable**: reference equivalence, correctly validated results, performance and memory/cancellation tests.

Phase 3 is a historical completed gate as of version 0.4.0. The implementation and measured verification evidence are recorded in `docs/22_PHASE_3_SOLVER_ENGINEERING_REPORT.md`. Do not begin Phase 4 without an explicit user request.

## Phase 4 — responsive browser UI

- Fully implement five-destination interface, timetable workspace, priority editor, saved scenario controls and accessible interaction styling using only local HTML/CSS/vanilla JS.
- **Deliverable**: import → prioritize → generate → compare → save/export, via browser at localhost.

Phase 4 is a historical completed gate as of version 0.5.0. Its responsive workspace, scenario migration, browser evidence, verification results, and known limitations are recorded in `docs/23_PHASE_4_BROWSER_WORKSPACE_ENGINEERING_REPORT.md`. Do not begin Phase 5 without an explicit user request.

## Phase 5 — degree integration and FFCS recovery

- Semester plan editor, category accounting, alternatives/exclusions, five historical snapshot migrations and manual registered/full-section recovery.
- **Deliverable**: tested term planning and recovery flow.

Phase 5 is a historical completed gate as of version 0.6.0. The versioned degree domain, migration 0004, reviewed import pipeline, scenario transfer, browser workspace, exact recovery engine, verification evidence, and private-source limitation are recorded in `docs/24_PHASE_5_DEGREE_PLANNING_AND_RECOVERY_REPORT.md`. The five private historical snapshots were unavailable, so their actual contents were not migrated or published; the importer is complete and tested with public synthetic fixtures. Do not begin Phase 6 without an explicit user request.

## Phase 6 — VTOP userscript, interoperability and portable startup

- Manual-selection-first Tampermonkey collector that exports a reviewed JSON snapshot; no automated VTOP requests/registration.
- Excel/CSV, timetable and FFCSinator adapters, backup/restore, Windows PowerShell startup polish, optional Python runtime packaging only if later wanted.
- **Deliverable**: secure offline localhost release, documented no-Node installation and complete fixtures/tests.

## Codex rules

- User-selected architecture is authoritative: **no native desktop GUI or PySide6**; a small *local* Python HTTP server is required.
- No Node, npm, React, Next.js, Electron, external APIs, cloud database, third-party CDNs, VTOP credential capture or registration automation.
- Keep each phase end-to-end, test before claims, summarize changes and stop at explicitly requested gate.
- Verify supplied academic rules from sources; use `needs_review` with fail-closed strict planning when unverified.
- Keep `domain` and `solver` independent from HTTP routes. Preserve all source rows and semester context.
- Do not push commits to GitHub without express user approval.

Phases 0 through 5 are historical completed gates. Begin a later phase only when the user explicitly supplies its scope, and stop after the requested phase is independently reviewable.
