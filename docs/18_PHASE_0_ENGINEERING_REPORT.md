# Phase 0 engineering report

Completed: 2026-10-28. Scope was limited to the repository, canonical models, VTOP schema validation, localhost proof, Windows startup, and verification. No Phase 1+ importer, database, solver, timetable, degree planner, registration workflow, or userscript was implemented.

## Delivered architecture

- `pyproject.toml` defines a Python 3.12+ `src` package, console entry point, runtime dependencies, strict type checking, linting/formatting, and pytest configuration.
- `src/ffcs_studio/domain/` contains frozen dataclass models for curriculum courses, credit breakdowns, semester offerings, raw VTOP rows, teaching components, faculty sections, slot expressions, and import snapshots. It imports no web framework.
- `src/ffcs_studio/validation.py` validates Draft 2020-12 JSON Schema with date-time format checks and JSON Pointer diagnostics. Unknown component values remain valid source facts, round-trip unchanged, and produce a review warning.
- `src/ffcs_studio/cli.py` exposes `python -m ffcs_studio validate ...` and a loopback-only `serve` command with environment/CLI configuration.
- `src/ffcs_studio/web/` contains a small FastAPI app, semantic landing template, local CSS, and vanilla JavaScript ES module. `/health` returns readiness and version metadata; unknown routes return a stable JSON error envelope.
- The ASGI security boundary validates loopback Host values, rejects foreign Origins on state-changing methods, limits declared request bodies, adds a restrictive Content Security Policy and related headers, and never exposes a filesystem directory beyond the dedicated static asset folder.
- `scripts/start.ps1` checks `.venv`, Python 3.12+, dependencies, and port availability; starts Uvicorn on `127.0.0.1`; waits for readiness; opens the browser by default; and cleans up its child process. `-NoBrowser` supports automated checks without changing the default user flow.
- `.gitignore` excludes the local environment, test/cache output, databases, private data directories, archives, and Node/Next build trees.

## Verification evidence

All commands used the project-local Python 3.12.14 environment.

```text
.\.venv\Scripts\python.exe -m pytest
19 passed

.\.venv\Scripts\python.exe -m ruff check .
All checks passed!

.\.venv\Scripts\python.exe -m ruff format --check .
All files already formatted

.\.venv\Scripts\python.exe -m mypy src
Success: no issues found in 11 source files

.\.venv\Scripts\python.exe -m ffcs_studio validate examples\vtop_selected_theory_only.json examples\vtop_selected_eth_ela.json
OK ... 1 course(s), 5 allocation row(s)
OK ... 1 course(s), 12 allocation row(s)
```

The test suite covers course/raw-row/slot/component models, unknown values, lossless round trips, duplicate-looking row retention, both supplied fixtures, malformed JSON and records, precise error paths, rejection of unexpected sensitive fields, CLI exit codes, the landing page, health response, local static assets, a local OpenAPI contract with CDN-backed interactive docs disabled, stable 404 JSON, security headers, hostile Host/Origin rejection, request-size rejection, and non-loopback bind refusal.

A live Uvicorn smoke run on `127.0.0.1:8877` returned `status=ready`, HTTP 200 HTML containing `FFCS Studio is running`, and HTTP 200 local CSS. The actual PowerShell startup script was also run on port 8878 with `-NoBrowser`; its readiness check passed and the port was closed after Ctrl+C. Browser opening remains the default but was intentionally suppressed during automation.

## Audit findings and limitations

- The supplied directory was not a Git working tree, so Git status/history/remotes could not be audited and no commit or push was made. See `docs/17_PHASE_0_AUDIT.md`.
- The system Python is 3.10.11; `.venv` was created with the available local Python 3.12.14 runtime. A normal user setup still requires an installed Python 3.12+ as documented in `README.md`.
- `schemas/degree-snapshot.schema.json` is referenced but absent; the no-subject VTOP fixture described by the test strategy is also absent. Neither contract was invented in Phase 0.
- SQLite configuration has a safe local data-directory setting, but Phase 0 creates no database. Schema/migrations, atomic import preview/commit, source digests, snapshot diffing, and backups belong to Phase 1.
- There are no upload or state-changing product endpoints yet. The global declared-body limit and Origin policy are defense-in-depth; Phase 1 must add streaming upload enforcement, media/type checks, CSRF protection for writes, transaction rollback, and safe filename/path handling.
- No academic slot time, faculty pairing, credit limit, prerequisite, equivalency, or curriculum ambiguity was resolved. Unknowns remain fail-closed future solver inputs as listed in `docs/15_OPEN_QUESTIONS.md`.
- Dependency licence review and a project licence decision remain open before distribution.

## Phase 1 entry requirements

Phase 1 should preserve the existing canonical/raw split and implement JSON/CSV import as validate → preview → explicit atomic commit. It needs a versioned SQLite schema and migrations under the configured local data directory, immutable import snapshots and SHA-256 digests, idempotency, change reconciliation without cross-semester merging, backup/rollback, row-level review reports, and a simple real-data browser import screen under `/api/v1/imports/`. The missing degree schema and legacy adapters should be designed only from supplied source snapshots, not guessed. Phase 1 must not begin the timetable solver or certify unverified slot/pairing rules.
