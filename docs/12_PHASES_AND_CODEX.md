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

## Phase 2 — verified Vellore calendar and component rules

- Versioned slot calendar from official verified source only; component parser, interval overlap, faculty pairing rule states, ETL/ETP/TH handling.
- Explicit uncertain/unknown validation results; never mark unverified timetable valid.
- **Deliverable**: rule suite and issue tracking pass.

## Phase 3 — solver and ranking

- Tiny brute-force reference, optimized lazy search/bitset/MRV/pruning, top-K and accurate counting separately.
- Deterministic priority ranking, explanations, `cancel` and progress jobs exposed through localhost.
- **Deliverable**: reference equivalence, correctly validated results, performance and memory/cancellation tests.

## Phase 4 — responsive browser UI

- Fully implement five-destination interface, timetable workspace, priority editor, saved scenario controls and accessible interaction styling using only local HTML/CSS/vanilla JS.
- **Deliverable**: import → prioritize → generate → compare → save/export, via browser at localhost.

## Phase 5 — degree integration and FFCS recovery

- Semester plan editor, category accounting, alternatives/exclusions, five historical snapshot migrations and manual registered/full-section recovery.
- **Deliverable**: tested term planning and recovery flow.

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

## First Codex task (copyable)

> Inspect the local repository and all the documents, beginning with `AGENTS.md`, `docs/00_START_HERE.md`, `docs/10_IMPLEMENTATION.md`, `docs/12_PHASES_AND_CODEX.md` and `docs/16_LOCALHOST_RUNTIME_AND_SECURITY.md`. Implement **Phase 0 only** as a Python + FastAPI localhost website, with canonical typed course/allocation models, schema validator CLI, proper local startup script, `/health` endpoint, a minimal browser landing page, sanitized fixtures and tests. Serve at `http://127.0.0.1:8765`. Do **not** build PySide6/Qt, desktop executable, Node app, heavy UI, solver or live Tampermonkey automation. Actually run the tests and HTTP smoke checks and report precisely what was tested. Do not push GitHub changes without approval.
