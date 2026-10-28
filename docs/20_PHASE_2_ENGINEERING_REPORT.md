# Phase 2 engineering report — slot calendar and academic components

## Outcome

Phase 2 adds the evidence-aware local rule layer needed before any global timetable solver. It does not start Phase 3. The implementation resolves raw slot expressions only against an explicitly selected immutable calendar version, detects clashes using half-open minute intervals, distinguishes malformed expressions from calendar-unknown tokens, and exposes uncertainty instead of manufacturing academic facts.

No authentic official VIT Vellore Winter Semester 2026–27 timetable or pairing source exists in the repository or supplied local references as of 2026-10-28. Consequently, `examples/sample_slot_calendar_DRAFT.json` is intentionally synthetic, names its non-official semester, and is stored as `draft_unverified`. It must not be used for real registration decisions.

## Domain model and correctness boundaries

- `domain/calendar.py` defines weekdays, meeting kinds, evidence, verification states, atomic slots, weekly intervals, profiles, strict parse results and resolution results.
- Intervals are half-open `[start, end)`. Touching boundaries do not clash; any positive same-day overlap does.
- Combined expressions preserve exact raw text and token order. Empty tokens such as `A1++TA1` are malformed. Well-formed absent tokens are `unknown_to_selected_calendar`.
- A calendar cannot be constructed as `official_verified` without an official-document evidence reference plus reviewer and review time. The JSON import service also downgrades unsupported official claims to `user_supplied` with a warning.
- `domain/conflicts.py` returns `confirmed_clash`, `no_clash`, or `unresolved`. Unknown inputs never become a false no-clash result.
- `domain/component_rules.py` keeps curriculum types (`TH`, `ETL`, `ETP`, `LO`, `ELJ`, `PJ`, `SS`) separate from observed allocation types (`TH`, `ETH`, `ELA`, `EPJ`, `SS`). EPJ is not treated as a lab.
- `domain/workload.py` calculates unioned weekly minutes, meeting count and explicit session count from resolved intervals. It contains no `L-count / 2` heuristic.
- One-course candidates are bounded. Required multi-component choices are emitted only when exact revision-scoped allocation-pair states permit them; unknown and forbidden pairings are not cartesian-producted into candidates.

## Persistence and compatibility

Migration `0002_slot_calendars.sql` is additive and leaves `0001_initial.sql` unchanged. It stores calendar identities and immutable versions separately, atomic slots and occurrences, active selection, audit events, and pairing rules scoped to one offering revision and exact allocation IDs. Prior calendar versions remain queryable after a new version becomes active.

Calendar schema `2.0.0` records explicit evidence separately from verification status and supports session identifiers. Schema `1.0.0` remains readable through a compatibility adapter; its source text is marked legacy/unreviewed and cannot establish official verification.

## Local API and browser interface

The localhost API provides:

- `GET /api/v1/calendars`
- `POST /api/v1/calendars/validate`
- `POST /api/v1/calendars/preview`
- `POST /api/v1/calendars/commit`
- `POST /api/v1/calendars/{calendar_id}/select`
- `GET /api/v1/calendars/{calendar_id}`
- `POST /api/v1/slots/resolve`
- `POST /api/v1/conflicts/check`
- `GET /api/v1/offerings/{offering_id}/components`
- `GET /api/v1/offerings/{offering_id}/registration-options`

All writes retain the Phase 1 loopback, same-origin, request-size and CSRF boundary. The browser Slot & Component Inspector performs the real validate → preview → commit/select flow and shows raw JSON resolution and clash evidence. It uses only local HTML, CSS and vanilla JavaScript.

## Verification

Verification completed on Windows 11 with Python 3.12.14:

- `python -m pytest`: **84 passed**.
- `python -m ruff check .`: passed.
- `python -m ruff format --check .`: 72 files already formatted.
- `python -m mypy`: strict checks passed for 43 source files.
- `python -m pip check`: no broken requirements.
- Real localhost browser smoke test at `http://127.0.0.1:8765`: health ready, application 0.3.0, database schema 2; selected the bundled synthetic JSON; validate reported `draft_unverified`; preview reported 4 atomic slots and 5 intervals; commit selected the immutable version; `A1` versus `L1` returned `confirmed_clash` with the exact Monday 480–530 overlap.
- Final browser reload after the component-inspector update reported no JavaScript console errors.

The suite covers strict parsing, multi-day resolution, deduplication, unknown tokens, half-open boundaries, minute overlap, workload union/session counts, official-evidence gating, vocabulary separation, bounded candidates, pairing states, migration preservation, immutable versions, v1 compatibility, idempotent commits, API security and the complete calendar API workflow.

## Known limitations and next gate

- The real Winter Semester 2026–27 Vellore calendar remains blocked on an authentic reviewable source.
- Curriculum course type is not present in the Phase 1 VTOP allocation capture. The component endpoint therefore reports it as unknown unless a caller explicitly supplies a reviewed type when requesting registration options.
- No pairing rules are preloaded because no official pairing evidence was supplied.
- Phase 2 creates one-course candidates only. It does not search across courses, rank timetables, or claim registrability. Those belong to a separately requested Phase 3.
