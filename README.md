# FFCS Studio

FFCS Studio is an offline-first planning application served only on the local computer. Phase 0 provides the Python foundation, canonical VTOP capture models and validator, and a minimal browser page at `http://127.0.0.1:8765`. It does **not** yet include the timetable solver, degree planner, registration recovery workflow, or Tampermonkey collector.

The approved stack is Python 3.12+, FastAPI/Uvicorn, SQLite in later persistence phases, and local HTML/CSS/vanilla JavaScript. There is no Node.js, npm, React, Electron, PySide6/Qt, CDN, cloud database, external API, or runtime internet requirement.

## Windows 11 setup

Open PowerShell in this repository and confirm Python 3.12 or newer is installed:

```powershell
py -3.12 --version
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'
```

Package installation may use the internet once. Normal application startup and rendering are local and offline.

## Start the local website

```powershell
.\scripts\start.ps1
```

The script checks Python and dependencies, refuses an occupied port, starts the server on `127.0.0.1`, waits for `/health`, and opens the default browser. Keep the PowerShell window open. Press `Ctrl+C` there to stop the server and its child process.

To use a different local port:

```powershell
.\scripts\start.ps1 -Port 8877
```

The direct development command is:

```powershell
.\.venv\Scripts\python.exe -m ffcs_studio serve --host 127.0.0.1 --port 8765
```

Phase 0 rejects non-loopback bind addresses. Optional configuration variables are `FFCS_STUDIO_HOST`, `FFCS_STUDIO_PORT`, `FFCS_STUDIO_MAX_REQUEST_BYTES`, and `FFCS_STUDIO_DATA_DIR`. No database is created in Phase 0.

## Validate VTOP JSON

Validate either supplied sanitized fixture:

```powershell
.\.venv\Scripts\python.exe -m ffcs_studio validate examples\vtop_selected_theory_only.json
.\.venv\Scripts\python.exe -m ffcs_studio validate examples\vtop_selected_eth_ela.json
```

Schema errors include JSON Pointer locations and produce exit code `1`. Invalid configuration/schema setup produces exit code `2`. Unknown institutional component values are retained, reported as review warnings, and still produce exit code `0` when the JSON contract is otherwise valid.

## Development checks

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy src
```

Project architecture and source constraints are in `AGENTS.md` and `docs/`. The initial gap/migration review is recorded in `docs/17_PHASE_0_AUDIT.md`. Do not place raw VTOP HTML, authentication data, student-identifying data, private source archives, databases, `node_modules`, or `.next` output in this repository.
