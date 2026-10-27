# Phase 1 engineering report

Completed: 2026-10-28. Phase 1 delivers persistent, lossless course-data importing and browsing. It does not begin timetable solving, academic pairing, degree planning, VTOP registration, or live seat collection.

## Binding architectural decisions

- SQLite remains entirely local under `Settings.data_dir`; the default database is `%LOCALAPPDATA%\FFCSStudio\ffcs_studio.sqlite3`, and tests use isolated temporary directories.
- Schema version 1 uses explicit migrations and separates import snapshots, global course identities, semester offerings, immutable offering revisions, raw allocation rows, warnings, and reconciliation events. Active revisions are pointers; history is never overwritten.
- Every incoming file is a partial semester update unless a future explicit full-replacement operation says otherwise. Omitted courses remain active. An overlapping `(campus, semester, category, course code)` replaces only that offering's active revision after preview.
- Raw file SHA-256 records byte provenance. A canonical semantic SHA-256 ignores JSON whitespace/key formatting while preserving course/allocation array order. Repeated semantic imports do not duplicate effective data.
- Validation, preview, and commit are distinct. Bounded validated records and previews are kept in a size-limited, expiring in-memory store. Commit uses a random preview capability, verifies the database revision, and applies the exact reviewed data atomically.
- JSON uses the packaged public schema and the same validation implementation as the CLI. CSV uses the documented flat columns, preserves source ordering and raw strings, and requires explicit campus, semester, capture time, and user-supplied provenance metadata when a sidecar is absent.
- Upload APIs accept bounded raw request bodies rather than filesystem paths or multipart parsing. The ASGI receive stream independently enforces `Settings.max_request_bytes`, including absent or misleading `Content-Length`.
- Unsafe requests require a per-process application CSRF token in a custom header, a valid loopback Host, same-origin Origin/Referer when present, and acceptable Fetch Metadata. There is no account, cookie, cloud, CORS, or internet dependency.
- Course browsing uses parameterized, indexed SQLite queries with stable ordering and pagination. Allocation rows are source evidence only; Phase 1 creates no faculty pairing or registrable timetable options.

## Persistence and migration architecture

`Database` owns short-lived SQLite connections, enables foreign keys and the configured busy timeout on every connection, initializes WAL mode, applies packaged migrations, verifies `quick_check` and `foreign_key_check`, and exposes explicit transaction/connection contexts. The active database is `Settings.database_path`, normally `%LOCALAPPDATA%\FFCSStudio\ffcs_studio.sqlite3`; it is not repository data.

Migration `0001_initial.sql` creates:

- `schema_migrations` and `app_state` for schema/data revisions;
- immutable `import_snapshots` with raw and semantic SHA-256 digests;
- catalogue-level `courses`;
- semester/campus/category/code-scoped `offerings` with an active-revision pointer;
- immutable `offering_revisions` and ordered, lossless `allocation_rows`;
- `import_warnings` and ordered `reconciliation_events` for review/audit history.

Foreign keys use restrictive deletion for academic evidence. Allocation uniqueness is only `(revision_id, allocation_ordinal)`, so identical details and repeated source row numbers are never silently discarded. Search fields are additive case-folded columns; raw category, code, title, slot, venue, faculty, component, source row, and ordinals are retained.

Before an existing database is migrated, and before each non-duplicate import commit, SQLite's online backup API creates a consistent file in `<data_dir>\backups`. The ten newest backups are retained. `Database.restore_backup` accepts only a file inside that configured backup directory and verifies integrity after restoration.

## Import formats and provenance

JSON uses packaged `vtop-export.schema.json` v1 and the same byte/mapping validation path as the CLI. UTF-8 BOM is accepted. JSON schema diagnostics preserve JSON Pointer locations; unknown component values remain valid with warnings.

CSV supports the documented nine-column flat contract, UTF-8/BOM, standard quoting, commas in names/titles, combined slots, blank lines, mixed and unknown components, repeated source rows, and row-order preservation. It requires explicit campus, semester, and timezone-aware capture time from a sidecar/header or the UI because those facts are absent from the flat rows. CSV provenance is `manual-csv-upload` with `metadata_origin=user_supplied` or `sidecar`; it is never mislabeled as a Tampermonkey JSON capture. A sidecar may explicitly list zero-allocation courses.

Both adapters produce `ImportSnapshot`/`SemesterOffering` records while retaining their different source formats and provenance. Credits and curriculum course type are stored/displayed as not supplied; EPJ is never promoted to ETP.

## Validate, preview, reconcile, and commit

1. `validate` accepts a bounded raw request body, checks safe plain filenames/media type, validates the entire document, computes raw/canonical SHA-256 digests, and retains a bounded expiring prepared record.
2. `preview` compares each incoming course only with the active offering for the same campus, semester, category, and code. It records the current database data revision and returns a random capability token.
3. `commit` takes only that preview token. Under a process commit lock and `BEGIN IMMEDIATE`, it rechecks the data revision, inserts the immutable snapshot/revisions/rows/warnings/events, advances the data revision, and updates only the submitted offerings' active pointers.
4. Any exception rolls back the transaction. A changed database revision returns a stale-preview conflict; expired/evicted capabilities return a gone response.

Omitted courses are untouched. Matching course content is classified as unchanged; changed title/rows create a new revision and preserve the old one. Reconciliation uses exact multisets plus unique `source_row` matching to report added, removed, and modified evidence. Pure order changes are reported separately and do not appear as content additions/removals. Ambiguous repeated source rows are preserved and warned rather than forcibly paired.

Canonical JSON sorts object keys but does not reorder course/allocation arrays. Whitespace and object-key formatting changes therefore remain idempotent while meaningful source order remains significant. An existing semantic digest returns `already_imported` without a new snapshot, backup, active record, or data revision.

## Local API v1

The UI uses these real endpoints; no frontend dataset or localStorage persistence exists.

| Method | Endpoint | Result |
|---|---|---|
| POST | `/api/v1/imports/validate` | Validated counts, warnings, expiring validation token |
| POST | `/api/v1/imports/preview` | Per-course reconciliation and expiring preview token |
| POST | `/api/v1/imports/commit` | Atomic commit/already-imported outcome |
| GET | `/api/v1/imports` | Paginated import history |
| GET | `/api/v1/imports/{id}` | Snapshot provenance and warnings |
| GET | `/api/v1/imports/{id}/diff` | Audited reconciliation events |
| GET | `/api/v1/semesters` | Active semester/campus counts |
| GET | `/api/v1/offerings` | Paginated/searchable/filterable active offerings |
| GET | `/api/v1/offerings/{id}` | Course, provenance, warnings, and missing metadata |
| GET | `/api/v1/offerings/{id}/allocations` | Every current source row in captured order |

Upload content is the raw JSON/CSV body. `X-FFCS-Filename` supplies only a sanitized display filename. CSV metadata uses the documented `X-FFCS-*` headers or JSON `X-FFCS-Metadata`. Request models constrain tokens/page sizes/filter lengths. Query values are bound parameters, ordinary lists are limited to 100 rows/page, ordering is deterministic, and errors expose no database path or traceback.

## Security protections

- Loopback-only runtime configuration and Host allow-list resist remote binding and DNS rebinding.
- The ASGI receive wrapper counts actual chunks and returns structured HTTP 413 before bytes beyond `Settings.max_request_bytes` reach request parsing. This works with absent or misleading `Content-Length`; excessive declared length is rejected early.
- Every unsafe request requires the per-process random token embedded in the same-origin page and sent as `X-FFCS-CSRF`. Fetch Metadata, Origin, and Referer are checked when supplied; foreign values are rejected.
- Upload media types are allow-listed, filenames cannot contain paths, and no API accepts a server filesystem path.
- CSP, frame denial, MIME sniffing denial, permissions policy, and no-referrer headers apply to normal and middleware error responses. FastAPI docs use no CDN and the application makes no remote runtime request.
- SQL is parameterized. Database errors and unexpected failures use generic JSON envelopes.

## Browser interface

The local page provides an explicit file-selected → validating → valid/warning/error → preview → committing → saved/duplicate/stale flow. Commit remains disabled until a valid preview exists. The preview shows exact counts and per-course changes. CSV-only metadata controls clearly label values as user-supplied.

The explorer uses server-side semester selection, code/title search, category/component filters, and pagination. A course opens as one offering with all exact rows in `Slot | Venue | Faculty | Component` form plus provenance, warnings, and the explicit credits/curriculum-type unknown state. It does not generate theory/lab combinations.

## Verification evidence

The project-local Python 3.12.14 environment produced:

```text
.\.venv\Scripts\python.exe -m pytest -q
42 passed

.\.venv\Scripts\ruff.exe check .
All checks passed!

.\.venv\Scripts\mypy.exe src
Success: no issues found in 30 source files
```

The final delivery also runs Ruff formatting, `pip check`, both CLI fixtures, and installed-package/resource checks. Tests use isolated temporary databases and cover database creation/repeat migration/integrity/rollback/failure/restart, 5- and 12-row JSON fixtures, malformed/schema/unknown/duplicate/zero-row cases, CSV BOM/quoting/metadata/errors, partial/idempotent/updated/reordered/campus/semester/stale/failed reconciliation, streaming security, CSRF/origin/Host/media/filename handling, complete HTTP import/browse/filter/history, and restart persistence.

A real visible localhost browser run selected `vtop_selected_eth_ela.json`, validated 1 course/12 rows, previewed 1 new course/12 added rows, explicitly committed it, filtered the SQLite-backed explorer to ELA, and opened CSI3002. The detail showed all six ETH and six ELA rows, exact faculty/rooms/combined slots, source filename, capture time, commit time, and import identity. This was not simulated API data.

## Performance measurement

A synthetic import containing 250 courses and 2,500 allocations (290,461-byte JSON) was measured through validation, reconciliation, backup, and commit using `time.perf_counter` and `tracemalloc`: 1.4039 seconds elapsed and 2.32 MiB peak traced Python memory on this Windows development host. Ordinary listing remains paginated and does not load import history or all allocations.

## Known limitations and deferred sources

- The five historical degree snapshots, former planner inputs, FFCSinator source format, and cited 27-course workbook are absent. No unverifiable adapter, degree schema, or 181-row claim was invented.
- Full-semester replacement is not supported. Every v1 capture is a partial update; a future destructive replacement needs explicit scope, confirmation, and audit semantics.
- Temporary preview capabilities are process-local and intentionally expire; restarting the server requires revalidation/review.
- The process-level lock serializes commits in one local server. SQLite `BEGIN IMMEDIATE`, busy timeout, and stale data revisions protect database state; multi-process serving is not a supported mode.
- The API offers backup creation/validated restore primitives but no browser restore workflow in Phase 1.
- Sorting inside a course remains source order. Course-list filtering/pagination is server-side; arbitrary allocation sorting is deliberately omitted so provenance order stays primary.

## Academic boundaries and Phase 2 readiness

Unknown component types remain review-only. `NIL` is a valid source string, not an import error. Nothing here certifies component pairing, faculty coupling, slot-to-time resolution, opposite-shift rules, prerequisites, credit eligibility, registrable candidates, clash freedom, or availability.

Phase 2 can build read-only planning concepts above stable offering/revision/allocation identities and raw provenance. Before solver behavior, it still needs verified institutional slot mappings and explicit policies for component compatibility/pairing. The persistence and domain layers remain independent of FastAPI/HTML and are ready for those additive rules without rewriting source evidence.
