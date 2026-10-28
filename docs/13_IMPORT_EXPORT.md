# Import/export interoperability and migration maps

## Primary exchange: VTOP JSON

`schemas/vtop-export.schema.json` contains the exact envelope. High-level shape: `schema_version`, `source`, `campus`, `semester_label`, `captured_at`, `courses[]`, each course with `category`, `course_code`, `course_title`, `allocations[]`, each with `slot`, `venue`, `faculty`, `course_type`, `source_row`. Keep raw `course_type`; separate class `curriculum_type` only after matching curriculum.

The exported JSON may contain only `capture tool version`, `date`, `campus`, `semester`, `category`, course code/title, and allocation columns + row ordinal. No VTOP page HTML, login ID or hidden fields.

## CSV flattening

`semester_label,category,course_code,course_title,source_row,slot,venue,faculty,course_type` (UTF-8, quoted fields as necessary). Sidecar `metadata.json` stores contract version and capture time if CSV cannot represent it. Empty rows for zero-allocation courses must be explicitly signaled in metadata to avoid losing them.

## Human-readable Excel

Generate workbook from local canonical snapshot, not as canonical input. Separate sheets PC/PE/UC/UE/SPE/BC/NC as present, each subject named header followed by `Slot | Venue | Faculty | Course Type`, separate stacked tables, source timestamp/page where known. Additional searchable `ALL_ROWS` tab optional for filtering; avoid duplicate hidden data sources. If course metadata absent from VTOP, mark `Not supplied` instead of guessing credits/type.

## Legacy FFCSinator TypeScript adapter

Input shape from inspected `data/MID_5YEAR/*.ts` uses keys `CSI3001L - ...` (theory), `CSI3001P - ...` (practical) and arrays of `{slot,venue,faculty}`. Import through safe tokenizer/parser or a one-time **controlled converter**, not `eval` or arbitrary TypeScript execution. Category derived from filename mapping `ProgrammeCore` -> PC, `ProgrammeElective` -> PE, `SpecializationElective` -> SPE, `UniversityCore` -> UC, `UniversityElective` -> UE. `L/P` suffix is adapter-specific. **Do not assume** a raw VTOP subject code naturally ends in `L`/`P`.

Mapping from VTOP: `TH/ETH/SS/EPJ` normally becomes legacy suffix `L` for backward compatibility; `ELA` becomes `P`; preserve missing course component data and flag unsupported legacy semantics. This legacy mapping is **lossy** (e.g. EPJ vs ETH can collapse) unless a sidecar JSON retains `course_type`, `NIL`, pairing metadata and the original source row.

Be careful of snapshots from prior **Fall** semester being imported into **Winter**: database isolates by source semester.

## Degree JSON adapter

- `catalog[]`: course code/title/type/credit breakdown + content and `id` fields.
- `completed[]`: completed subject code, semester, credits, category, grade where provided.
- `plan['5']...plan['10']`: course objects identified by `courseId`, not `code`, with status/availability.
- `offerings`: availability metadata by term/course; `offerings['5']` in saved snapshots is not an official winter 2026 offering.
- `updatedAt`: use to label timeline (not as evidence that the current semester had these options).

Export one consolidated canonical degree snapshot with version; keep original JSONs for audit.

Phase 5 implements the version-6 reader as a reviewed, idempotent snapshot import. It preserves original `courseId`, source order, source digest, explicit source sequence, the complete source JSON, and each snapshot's independent plan. Comparison reports additions, removals, moves, and status changes; activation creates a named degree timeline and never unions another snapshot. Unknown references fail validation. A canonical curriculum schema is published at `schemas/curriculum-catalog-v1.schema.json`; its catalogue records remain distinct from semester offering rows.

The private historical files named in `reference/source_manifest.json` were not available in the designated project references during Phase 5. Only the conspicuously synthetic public fixture was committed, and no actual student completion or registration record is included.

## Compatibility direction

For each format implement reader and writer separately with golden fixtures and precise warnings of fields dropped; full fidelity should be guaranteed only for canonical JSON. `data.zip` is a legacy schema **sample**, not official current data.

## Phase 6 implemented contracts

- Canonical semester JSON is generated from active SQLite offering revisions and conforms to VTOP schema `1.0.0`; it is the only full-fidelity course exchange.
- CSV round-trips with a metadata sidecar, including zero-allocation course metadata. CSV and XLSX neutralize spreadsheet formula prefixes without altering canonical JSON.
- XLSX contains category sheets plus `ALL_ROWS`, frozen headers and filters. It is an inspection/export format, not a canonical importer.
- FFCSinator ZIP emits documented category `.ts` files plus `ffcs-studio-sidecar.json`. The reverse adapter accepts only one bounded object literal containing strings, arrays and objects; it never invokes Node, `eval`, imports, functions, templates, environment access, or expressions. It records `legacy-ffcsinator` provenance and enters the ordinary validate → preview → commit pipeline.
- Scenario export envelopes import only through strict validation. Original IDs are audit metadata; commit always creates a new scenario and never overwrites an existing identity.
