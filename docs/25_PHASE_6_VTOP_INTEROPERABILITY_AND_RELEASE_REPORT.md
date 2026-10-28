# Phase 6 — VTOP interoperability and Windows release report

Date: 2026-10-28
Release: 0.7.0
Baseline: `5a2b4e39b33a81205e0834377cf99839ec2cc44e`

## Delivered workflow

Phase 6 completes the local workflow from a user-reviewed VTOP allocation table to FFCS Studio without automating portal navigation or registration:

1. The user signs in normally, selects a semester/category/course, reviews the visible table and captures it with the standalone userscript.
2. The collector exports schema-valid canonical JSON or flattened CSV plus metadata.
3. FFCS Studio validates, previews and atomically commits the capture.
4. The existing planner, scenario store, degree workspace and recovery engine operate on the committed local revisions.
5. Semester data can be exported as JSON, CSV, XLSX or a lossy FFCSinator compatibility ZIP; scenarios can be shared as independent copies; the complete SQLite state can be backed up and restored.

No Node/npm, Electron, cloud service, CDN, external API, analytics, VTOP credential capture, hidden request, registration action or runtime internet connection was added.

## Collector installation and permissions

Install `integrations/vtop/ffcs-studio-vtop-collector.user.js` manually in Tampermonkey after reviewing its source. Its metadata grants only `GM_getValue`, `GM_setValue` and `GM_download`, declares `@connect none`, and matches only `https://vtop.vit.ac.in/vtop/*`. A runtime host guard rejects other live hosts; the local fixture mode is explicit and sanitized. The collector neither reads nor stores cookies, passwords, authentication headers, CSRF/hidden fields, raw HTML, student identifiers or unrelated browser storage.

The panel is a compact keyboard-operable shadow-DOM control with current selection, state, row/course counts, latest capture/time, diagnostics, review/remove/recapture/reset and explicit JSON/CSV export actions. Export occurs only after a user action.

## Supported VTOP structure and stable asynchronous capture

The supported observed structure is `select#curriculumCategory`, `select#courseId`, `#courseListFragement`, `#courseDetailFragement`, and a visible allocation table headed `Slot Detail`, `Venue`, `Faculty`, `Course Type`. The historic `Fragement` spelling is intentional. Queries tolerate duplicate IDs by inspecting visible candidate fragments and use live control values plus selected visible text.

Selection changes invalidate ready state. A scoped `MutationObserver` follows the detail fragment's parent, with debounce and stability checks; there is no body-wide observer, interval loop, per-frame polling or DOM serialization. Parsing verifies exact headers, captures a selection version before and after extraction, and refuses stale/mixed data. When the page offers no reliable course/table identity, a manual association acknowledgement is required. Zero-row captures require separate acknowledgement. Unknown components are retained and flagged; extra columns block version-1 capture rather than being dropped silently.

Capture identity is campus + semester + category + course code. Duplicate allocation rows and original order are preserved. Recapture shows change information, requires confirmation and keeps three bounded prior versions without appending stale rows. Storage is capped at 500 courses, 10,000 rows and 2 MiB.

## Source preservation and format contracts

Canonical JSON uses schema `1.0.0`, `source: vtop-tampermonkey`, timezone-aware capture time and no extra properties. It preserves category, raw course code/title and each ordered `source_row`, slot expression, venue, faculty and raw component type. This is the authoritative full-fidelity supported exchange.

CSV uses the existing nine columns and a metadata sidecar for campus, capture time, source provenance and zero-allocation courses. Embedded delimiters/newlines use normal CSV quoting. CSV/XLSX cells with formula-like prefixes are neutralized for spreadsheet safety, while canonical JSON keeps the original raw text. Regression checks compare field identities and order rather than counts alone.

XLSX is generated from committed SQLite revisions with a represented-category sheet and `ALL_ROWS`; it includes readable headers, filters, frozen panes and widths. It never invents credits or curriculum types and accepts no filesystem path from HTTP.

FFCSinator export emits recognized category TypeScript files plus `ffcs-studio-sidecar.json` containing exact canonical values, provenance and loss notes. The reverse parser accepts only one documented object-literal subset containing strings, arrays and objects. It rejects calls, imports, templates, environment access and other executable syntax and never invokes JavaScript/Node. Legacy `L`/`P` conveys only theory/practical side, so imported components are `UNKNOWN_LEGACY_*`, require review, and retain truthful `legacy-ffcsinator` provenance through the normal preview/commit pipeline.

## Scenario import

Scenario JSON import strictly rejects unknown envelope/document fields and unsupported versions. Validate and preview re-run current source-reference, calendar and solver checks. Existing source IDs are shown as conflicts but retained only for audit; commit always creates a new independent scenario using an explicit `create_new` or `duplicate` choice. Stale/incomplete imports can remain drafts and are never promoted to solver-ready by a trusted flag or title-based relinking.

## Backup and restore

Manual backup uses SQLite's online backup API while writes share a maintenance lock. Each backup receives a sidecar with format, application/schema version, timestamp, SHA-256, byte size, integrity result, reason and retention limit. The UI lists, downloads and reviews only files inside the configured backup directory; legacy files without matching sidecars appear invalid.

Restore requires the exact `RESTORE` phrase and matching reviewed checksum. It rejects corrupt or future-schema databases, quiesces solver/recovery workers, creates a pre-restore safety backup, stages a SQLite backup copy, atomically swaps the active database, applies supported forward migrations, verifies quick/foreign-key integrity and critical record counts, then recreates workers. Failure restores the safety copy. No archive extraction, arbitrary source/destination path or half-restored active file is permitted.

## Windows setup and packaging

`Start FFCS Studio.cmd` anchors to `%~dp0`, invokes the existing PowerShell launcher and applies `ExecutionPolicy Bypass` only to that child process. It makes no system policy change and installs/downloads nothing. `scripts/start.ps1` retains loopback-only binding, occupied-port detection, health readiness, browser opening, and Ctrl+C child cleanup. Python 3.12+ plus the documented virtual environment remains the supported installation.

The 0.7.0 wheel is built and inspected for migrations, JSON schemas, template, CSS, JavaScript modules, VTOP userscript and sanitized browser harness. It is installed into an isolated environment outside the source import path and the application factory/startup is exercised there.

## Privacy, security and dependency review

Static review and fixture assertions found no fetch/XHR monkey-patch, credentials, private portal HTML, student data, database, virtual environment or generated release artifact in the publish set. Loopback Host/Origin/CSRF controls continue to protect state-changing routes. Formula injection, executable TypeScript, malformed scenarios, corrupt/checksum-mismatched backups, path traversal and stale collector data have explicit negative tests.

XLSX support adds `openpyxl` (MIT) and `et-xmlfile` (MIT); `types-openpyxl` is development-only. Project-wide distribution licensing remains pending. This release does not claim a legally cleared signed installer, embedded Python runtime or public standalone binary.

## Automated and browser verification

Final release-gate results are recorded after the last clean-tree run:

- Pytest: **163 passed** in 15.23 seconds on the final post-browser gate.
- Ruff lint: **passed**.
- Ruff format check: **123 files already formatted**.
- Mypy strict mode: **passed, 69 source files**.
- Dependency check: **no broken requirements**.
- Wheel: **`ffcs_studio-0.7.0-py3-none-any.whl`, 199,394 bytes, SHA-256 `23d570c7679bd665c41bf3918e4f080bd379e5917e598606ebfbd5db83a1964a`**. Resource inspection passed; an isolated target import outside the checkout reported version 0.7.0, schema 4 and 91 routes.
- Windows launcher: started from a different working directory, returned the 0.7.0 health response on loopback port 8892, then shut down cleanly with the child process gone and port released.

Chrome executed the sanitized collector harness with asynchronous replacement, duplicate IDs, rapid course switching, duplicate rows, a four-period lab, unknown component, unexpected extra column and PII/CSRF-like irrelevant fields. All harness assertions passed and browser diagnostics were empty. The click workflow captured two courses/four rows and rejected stale/missing selections and unexpected columns.

Chrome also exercised FFCS Studio 0.7.0 with an isolated data directory: a public sanitized capture completed validate → preview → commit and displayed the exact twelve allocation rows; the XLSX route returned successfully; backup creation displayed schema/integrity/checksum metadata; a controlled second import changed the database; protected restore recovered the original one-course state; and the reloaded UI had no browser warnings/errors. Native file-picker automation was unavailable, so the same loopback-protected upload APIs supplied the public fixture while the resulting browser workflow and state were inspected. Destructive restore was invoked through the protected local API rather than an automated confirmation click.

## Performance review

`tools/benchmark_phase6.py` uses a sanitized 30-course/181-row dataset. Measured on the development Windows host:

| Operation | Median | Maximum |
| --- | ---: | ---: |
| Canonical JSON export | 4.188 ms | 5.137 ms |
| XLSX export | 284.811 ms | 292.584 ms |
| Legacy TypeScript parse | 4.235 ms | 4.873 ms |
| SQLite backup | 20.044 ms | 26.050 ms |
| SQLite restore | 55.164 ms | 62.680 ms |
| Application factory/startup | 67.428 ms | 77.038 ms |

Peak traced conversion memory was 2,890,934 bytes and the XLSX result was 24,617 bytes. The userscript does no continuous polling/global observation; its deterministic local harness confirmed responsive debounced updates. Solver memory/cancellation architecture is unchanged.

## Outstanding evidence and limitations

- The exact current authenticated VTOP allocation page was not available. The host scope was reviewed from current official VIT/VTOP material, but live route/DOM acceptance remains pending a user-supervised session. Simulated dynamic-DOM acceptance is not claimed as live-portal verification.
- Native browser file-picker automation was unavailable in the acceptance environment; public fixture upload used the protected loopback API and browser-visible results were checked.
- The private real 101-course curriculum and five historical degree snapshots remain unimported.
- The Fall 2026–27 calendar remains user-supplied, and the official Winter 2026–27 calendar remains unverified.
- ETH/ELA pairing remains evidence-dependent; NC accounting, some prerequisites/equivalencies and institutional policy values remain unresolved.
- Manual section availability is not real-time VTOP evidence.
- Legacy FFCSinator cannot represent exact component types, zero-allocation courses or all provenance without its sidecar.
- No public binary distribution is claimed until the project licence and bundled runtime terms are resolved.

These external evidence gaps do not weaken the fail-closed behavior: the application retains uncertainty, blocks strict planning when required evidence is missing and never upgrades software completion into an official academic claim.
