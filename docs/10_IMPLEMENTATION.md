# Engineering architecture — Python localhost website

## Binding technology choice (v0.2)

The user **does not want a desktop executable/application or a native PySide6/Qt interface**. Serve a browser-based website from a small local Python HTTP process. Recommended stack:

- Python 3.12+ for domain, imports, ranking, solver and local services.
- FastAPI + Uvicorn for HTTP API and static serving; Jinja2 for minimal server-rendered templates if useful.
- Vanilla HTML5, CSS and modern JavaScript ES modules (no transpilation/build step, npm, Node.js, Next.js, React, Electron or browser extension as UI shell).
- `sqlite3` for a local versioned SQLite database, `dataclasses` / typed domain objects, `pytest` for tests, `jsonschema` for input validation, `openpyxl` only if requested for Excel export.
- A separate small JavaScript Tampermonkey collector running on VTOP, exporting files for manual upload through the local website. No cross-origin background requests to VTOP.

The HTTP interface is bound by default to **127.0.0.1 only**, e.g. `http://127.0.0.1:8765/`. It is a *local* API/server, not a hosted service, cloud account, or internet dependency. Python package installation may require network once; routine runtime and rendering must be 100% offline with local fonts/assets.

## Suggested repository structure

```text
course-planner/
  AGENTS.md
  README.md
  pyproject.toml
  src/ffcs_studio/
    __init__.py
    cli.py                        # `python -m ffcs_studio serve|validate|...`
    domain/{models.py,types.py,credits.py,periods.py,rules.py}
    importers/{vtop_json.py,csv.py,legacy_degree.py,legacy_ffcsinator.py,xlsx.py}
    persistence/{db.py,repositories.py,migrations/}
    solver/{candidates.py,reference.py,optimized.py,ranking.py,explain.py}
    services/{degree.py,scenarios.py,reconciliation.py,export.py}
    web/
      app.py                      # FastAPI app factory / lifespan
      routes/{pages.py,imports.py,plans.py,scenarios.py,health.py}
      templates/{base.html,overview.html,planner.html,...}
      static/css/{tokens.css,layout.css,components.css}
      static/js/{api.js,planner.js,import.js,...}
      static/icons/
    resources/{calendars/,curricula/}
  userscript/vtop-allocation-collector.user.js
  tests/{fixtures/,unit/,integration/,api/,golden/,performance/}
  schemas/
  examples/
  docs/
  scripts/{start.ps1,dev.ps1,stop.ps1}
```

## Execution and UX

- `python -m ffcs_studio serve --host 127.0.0.1 --port 8765` runs the local server; users open `http://127.0.0.1:8765/`.
- Provide a Windows `scripts/start.ps1` that activates a local `.venv`, launches the server, checks readiness, then opens the URL in the default browser. Dev scripts can also be provided; do not hide errors or run silent perpetual daemon processes.
- Show errors if the port is in use, with a configurable alternative port. Ensure a single app instance uses only its own SQLite store; do not start multiple conflicting writers.
- Local user data must be outside version-controlled project paths, for example under `%LOCALAPPDATA%\FFCSStudio\`, with configurable path for portable operation. Never commit `*.db` with real records.
- A graceful shutdown from the terminal (`Ctrl+C`) must close worker tasks and database connections cleanly. Optional tray/EXE packaging is not a requirement.

## Boundaries

- `domain` and `solver` depend on **no FastAPI, HTTP, or browser code**.
- Imported files are strictly validated and normalized; raw rows and provenance retained; database changes are explicit atomic transactions.
- API handlers call services, not database queries copy-pasted into frontend handlers. All application computation, especially solver enumeration, happens in Python, not JavaScript.
- Client JavaScript only manages UI interaction, rendering and requests to localhost. Keep modules small and documented; never eval imported data.
- Long-running solver tasks use worker process with explicit cancellation, progress IDs and bounded top-K results. Use SSE or short interval status polling; close/disconnect gracefully. Do not block request handling, render one element per solution, or accumulate unbounded arrays.
- Browser refresh must not corrupt or silently lose saved scenarios. Persist intentional state in SQLite; track provisional unsaved edits visibly.

## HTTP API conventions

- `/health` reports local readiness and app/schema version, without private records.
- `/api/v1/imports/validate` checks file/schema and reports row-level errors.
- `/api/v1/imports/preview` returns proposed changes without committing.
- `/api/v1/imports/commit` commits only an explicitly approved validated import.
- `/api/v1/catalog` and `/api/v1/offerings` query normalized data.
- `/api/v1/plans` and `/api/v1/scenarios` support planning state later.
- `/api/v1/jobs/{id}` supports solver status/cancel later.

These paths are proposed stable contracts; document any justified changes. Return structured JSON errors, correct HTTP status codes, request limits and explicit schema versions. Add an OpenAPI-compatible API if FastAPI is used, but no runtime internet calls.

## Reliability and performance

- SQLite migrations, foreign keys, safe transactions, import hashes, backups and snapshot differences.
- Typed application errors; no silent drops of unsupported rows or unknown slots.
- Lazy candidate generation and bitsets for time, deterministic ranking, bounded top-K, cache invalidation and cancellation.
- Tests include pure-domain, source parsing, API request/response, upload security, static asset/offline rendering, browser navigation, concurrency and performance.
- Do not build a desktop GUI, use CDN fonts/scripts, or copy legacy `node_modules` and `.next` directories into the repository.
