# FFCS Studio

FFCS Studio 0.3.1 is an offline-first course-planning workspace served only on the local computer at `http://127.0.0.1:8765`. Phase 1 imports reviewed VTOP JSON or flattened CSV captures into SQLite. Phase 2 adds immutable semester-specific slot calendars, strict slot resolution, minute-accurate clash checks, component vocabulary, evidence-scoped pairing states, and conservative one-course registration candidates.

It never infers official slot times or faculty pairings. Calendar times resolve only from a selected local calendar version; unknown slots fail closed. Multi-component registration candidates require revision-scoped pairing evidence. The repository does not contain an authentic Winter 2026–27 VIT timetable, so the bundled calendar is conspicuously synthetic and draft-only. Phase 2 does not generate full timetables. The stack is Python 3.12+, FastAPI/Uvicorn, SQLite, and local HTML/CSS/vanilla JavaScript. There is no Node.js, npm, React, Electron, PySide6/Qt, CDN, cloud database, external API, or runtime internet requirement.

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

FFCS Studio rejects non-loopback bind addresses. Configuration variables are `FFCS_STUDIO_HOST`, `FFCS_STUDIO_PORT`, `FFCS_STUDIO_MAX_REQUEST_BYTES`, `FFCS_STUDIO_DATA_DIR`, `FFCS_STUDIO_DATABASE_NAME`, `FFCS_STUDIO_SQLITE_BUSY_TIMEOUT_MS`, and `FFCS_STUDIO_PREVIEW_TTL_SECONDS`.

## Import and browse course data

1. Open **Courses & Data** in the local website.
2. Select a VTOP JSON v1 file or documented flattened UTF-8 CSV file.
3. For CSV, enter the campus, semester, and capture time that the flat format cannot carry. These values are recorded as user-supplied.
4. Choose **Validate file**. Errors block import; warnings identify uncertain or duplicate-looking source evidence without discarding it.
5. Choose **Preview changes** and review new, updated, unchanged, added, removed, modified, and reordered records.
6. Choose **Commit import**. Nothing is persisted before this explicit step.

Each file is a partial capture by default. Omitted courses remain active. Changed data for one matching course creates a new immutable course revision; it does not replace the semester. Re-importing canonical-identical data reports that it was already imported and does not duplicate active records.

CSV columns are:

```csv
semester_label,category,course_code,course_title,source_row,slot,venue,faculty,course_type
```

The **Course explorer** reads SQLite through the local API. Select a semester, search by code or title, and filter by curriculum category or captured component. Open a course to see every source allocation in original order as `Slot | Venue | Faculty | Component`, together with source provenance, warnings, and missing metadata. These are source allocations—not automatically paired registration options.

## Local data and backups

The default database is `%LOCALAPPDATA%\FFCSStudio\ffcs_studio.sqlite3`. Set `FFCS_STUDIO_DATA_DIR` to use another local directory, including a path containing spaces. The active database is never created inside the repository unless that variable explicitly points there.

Before a schema migration or a non-duplicate import commit, the application creates a consistent SQLite backup under `<data directory>\backups` and retains the ten newest backups. For an additional manual backup, stop the server first and copy the database and `backups` directory together. Do not commit either to Git.

## Import and inspect a slot calendar

1. Open **Slot Inspector** and choose a calendar JSON file using schema `2.0.0`.
2. Validate the evidence and intervals, preview counts, then explicitly commit and select the immutable version.
3. Resolve an expression such as `A1+TA1`, or compare two expressions for minute overlap.

The API includes calendar list/detail/validate/preview/commit/select, slot resolution, conflict checking, offering component classification, and bounded one-course registration options. Legacy calendar schema `1.0.0` remains readable through a compatibility adapter. A user-provided `official_verified` string is not trusted by itself; reviewed official-document evidence is required, otherwise the claim is downgraded to `user_supplied`.

The repository includes `examples/fall_2026-27_weekday_slot_calendar_USER_SUPPLIED.json`, a non-identifying transcription of the user-supplied Vellore Fall Semester 2026–27 weekday grid. It contains 101 atomic codes and 115 exact half-open intervals, including all `L1`–`L60` lab codes. It is explicitly `user_supplied`, not independently verified institutional evidence, and must not be reused silently for Winter or another semester. The private registration reference used to check the grid remains under the Git-ignored `private/` directory and is never packaged.

For a privacy-preserving local check of a registration reference:

```powershell
.\.venv\Scripts\python.exe tools\validate_registered_timetable.py `
  --calendar examples\fall_2026-27_weekday_slot_calendar_USER_SUPPLIED.json `
  --registrations private\FFCS_Studio_Fall_2026-27_Registered_Components_LOCAL_ONLY.json
```

The command prints aggregate counts, contact minutes, session count and clash count only. It does not print course, faculty, room or registration-row details.

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
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy src
.\.venv\Scripts\python.exe -m pip check
```

Project architecture and source constraints are in `AGENTS.md` and `docs/`. Phase reports are `docs/19_PHASE_1_ENGINEERING_REPORT.md`, `docs/20_PHASE_2_ENGINEERING_REPORT.md`, and `docs/21_FALL_2026_WEEKDAY_CALENDAR_INTEGRATION.md`. Do not place raw VTOP HTML, authentication data, student-identifying data, private source archives, databases, virtual environments, `node_modules`, or `.next` output in this repository.
