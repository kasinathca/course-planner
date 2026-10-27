# Data model and persistence

## Canonical storage

SQLite (Python stdlib `sqlite3`) for fast indexed reads, transactions, change tracking and snapshots. Export/import is plain JSON (stable public contract). DB is **local only**, with startup migration, backup-before-import, FK enforcement and schema version.

### Logical entities

- `programme`: programme ID, campus, admission batch, curriculum revision.
- `category_rule`: category name, required target, allowable excess, count treatment, warnings, revision/effective date.
- `course`: stable internal `course_id`, institution code, canonical title, curriculum type, credit breakdown L/T/P/J, total credits, tags; **catalog independent of offerings**.
- `course_alias`: alternative codes/titles, provenance and equivalency vs alias vs mutually exclusive distinction.
- `course_prerequisite`: AND/OR groups, waivers, effective dates.
- `semester`: e.g. `2026-27-WINTER`, academic calendar profile ID.
- `offering`: course ID + semester ID + category at offering + import source/digest/status.
- `allocation_row`: immutable original row, slot text, faculty, room, raw course type, row order, timestamp/digest and provenance. No pairing inferred at this layer.
- `section`: normalized component section derived from an allocation row; all necessary dates/time blocks obtained by slot resolver.
- `section_pair_rule`: official/verified pairing edge between course components, its evidence status, and policy provenance.
- `registration_option`: compatible bundled selection for a course; calculated view/cache (not arbitrary independent theory/lab selection).
- `slot_calendar` / `slot_period`: versioned campus schedule and date exceptions.
- `student_completed_course`, `semester_course_plan`, `semester_lock`, `course_preference`, `faculty_preference`, `scenario`, `save_snapshot`, `availability_state`.
- `reconciliation_event`: changed/new/removed rows between distinct imports.

### Uniqueness and audit trail

Course codes can have documented alternatives and revisions; never use display name as unique ID. An allocation row identity should be `source snapshot ID + original ordinal` plus content hash, **not** merely `(faculty, slot)` because identical appearances can be meaningful. Within one snapshot, distinguish exact duplicate lines as `repeated source rows` and warn; avoid silent removal. Imports are idempotent for an identical source digest. Changed source snapshots coexist for audit; one marked active.

### Versioned contract

See `schemas/vtop-export.schema.json`, `schemas/slot-calendar.schema.json`, `schemas/degree-snapshot.schema.json`. `examples/` supplies fixtures. Use strict validation (JSON Schema in tests, native schema checks at runtime if avoiding extra deps). Mandatory fields absent -> quarantine/review, not default to invented values.

### Provenance and confidence

Every derived field has origin (`vtop_page`, `curriculum`, `imported_legacy`, `manual_override`, `derived`) and rule version. Classify schedule components as `verified`, `inferred_review_required`, `hypothetical`. Faculty identity normalization retains `raw_name` in addition to a display canonical name. No auto-merge across semesters.

### Core queries

- Offered course list by category / curriculum type / remaining-degree credit gap.
- Faculty+slot options per course; distinct components and pairing evidence.
- Compare import snapshots and count changed allocations.
- Required/optional courses with valid section options and time masks for solver.
- Saved scenarios and degree progress across semesters.

### Data migration

Import saved version-6 degree JSON `catalog/completed/plan/settings/offerings`, convert `plan[n][i].courseId`, preserve original `id`, `notes`, `availability`; preserve original snapshot files independently. Course catalog has 101 entries and at least one repeated course code for genuine alternatives. Do not count `planned` as `earned`. Missing historical offerings remain `unknown`, not `not offered`.
