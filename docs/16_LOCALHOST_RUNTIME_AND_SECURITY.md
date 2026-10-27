# Binding decision: website on localhost (supersedes older desktop instructions)

**Confirmed user decision**: The project is NOT to be a traditional installed app. The UI runs in Chrome/Edge or another normal browser as a website at `http://127.0.0.1:8765/`, served by a Python process on the user's laptop. It should work without an internet connection after one-time dependency installation. SQLite stores data on disk. Codex in the ChatGPT Windows app should edit the existing local project directory, not assume a VS Code extension workflow.

## Why this arrangement

- Entirely local and usable offline while preserving a professional browser-based interaction surface.
- No Node, npm, React, Next.js, Electron, browser-to-cloud service or native Qt GUI.
- No direct browser access to filesystem beyond user-selected imports/exports; local Python has controlled persistent storage.
- Computation happens in the Python process so expensive solver search never hangs the browser UI.

## Recommended runtime

`python -m ffcs_studio serve --host 127.0.0.1 --port 8765`

Expected endpoints: `GET /` returns readable HTML; `GET /health` returns a small JSON readiness payload. Static assets are served locally with no remote URLs. `scripts/start.ps1` can start the local server and open a browser tab. Later import/solve/status APIs should live under `/api/v1/`.

## Safety invariants

- Bind only to loopback; reject unrecognized Host and cross-origin state-changing requests; avoid permissive CORS and never allow remote page scripts to invoke destructive actions blindly.
- Apply request body/upload limits, file type and JSON schema validation. Never execute uploaded content or trust absolute paths supplied by web forms.
- Do not serve project reference archives, personal files, the whole database or arbitrary directory trees as static resources.
- Store SQLite in a configurable safe local data directory; use transactional migrations and backup before destructive changes. Use a clean shutdown and retain error logs without private account data.
- VTOP collector exports one file from a browser tab where the user is already signed in; the localhost site then manually imports it. No credential capture, hidden VTOP requests, or automated registrations.
- Solver tasks run in bounded workers with cancellation; plan count calculation is separate from enumerating top-K.

## Phase 0 testable definition

After installing local Python dependencies, the user can execute `scripts/start.ps1`, open the printed localhost URL in Chrome/Edge, see a minimal product page, hit `/health`, and use `python -m ffcs_studio validate <fixture>` to get a meaningful result and exit code. Tests must verify endpoints and file validation. No completed timetable UI is expected in Phase 0.

## Handling conflicting historical language

Any v0.1 reference to PySide6, Qt, desktop shell, native desktop installer, a ban on localhost server, or Node-only FFCSinator stack is obsolete as an implementation directive. Keep the academic and data analysis unless contradicted by newer source evidence. Do not delete provenance. This document controls the interface/runtime choice.
