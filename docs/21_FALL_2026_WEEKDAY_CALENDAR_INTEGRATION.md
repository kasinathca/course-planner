# Phase 2.1 engineering addendum — Fall 2026–27 weekday calendar

## Scope and provenance

Phase 2.1 integrates a non-identifying timetable grid supplied by the user for VIT Vellore, `Fall Semester 2026-27`. The packaged file is `examples/fall_2026-27_weekday_slot_calendar_USER_SUPPLIED.json` using calendar schema `2.0.0` and timezone `Asia/Kolkata`.

The source was manually transcribed from a user-supplied Fall registration/timetable view on 2026-10-28. It has not been checked against an independently reviewable institutional document, so its status remains `user_supplied`. This profile is not evidence for Winter Semester 2026–27 and is never propagated across semesters automatically.

The private registered-component reference remains in `private/`, which is Git-ignored. The repository, tests and this report contain only aggregate validation results; they do not publish the user's course choices, faculty, rooms or row-level registration data.

## Calendar coverage

- 101 distinct atomic codes and 115 weekly intervals.
- All laboratory codes `L1` through `L60`.
- 41 theory/special weekday codes.
- Monday through Friday only; zero Saturday/Sunday intervals.
- `V1` through `V7` retained as `other` because their academic meaning is not established.
- Absent codes such as `TBB1` and `TDD1` remain unresolved; no mapping is invented.
- `NIL` is not an atomic slot. It is treated as unscheduled only for an explicitly online/MOOC component.

## Exact timing decisions

All meetings use half-open intervals. The source grid's exact boundaries are retained rather than normalized to hours or assumed 50-minute units. In particular, laboratory pairs can have different contact totals:

- `L49+L50`: Thursday 14:00–14:50 and 14:51–15:40, 99 minutes, one session.
- `L51+L52`: Thursday 15:51–16:40 and 16:41–17:30, 98 minutes, one session.
- `L1+L2+L15+L16`: Monday 08:00–08:50 and 08:51–09:40, Wednesday 09:51–10:40 and 10:41–11:30, 197 minutes, two sessions.

The local API now includes `day_name`, `start_time`, `end_time` and `duration_minutes` alongside numeric day/minute values so the browser inspector presents auditable weekday and clock labels without discarding the canonical integers.

## Known resolution and conflict evidence

Regression tests cover:

- `A1+TA1`: Monday 08:00–08:50, Wednesday 09:00–09:50, Friday 10:00–10:50.
- `B1+TB1`: Monday 11:00–11:50, Tuesday 08:00–08:50, Thursday 09:00–09:50.
- `A2+TA2`: Monday 14:00–14:50, Wednesday 15:00–15:50, Friday 16:00–16:50.
- Confirmed clashes for `A1`/`L1`, `A1`/`L14`, and `TA1`/`L27`.
- Confirmed no-clash for `A1`/`A2`.

## Private registered-timetable check

The local-only reference was checked using `tools/validate_registered_timetable.py`. That tool imports the calendar through the actual validation → preview → commit → activation services in a temporary SQLite database, reloads the stored profile, verifies exact campus/semester equality, resolves every physical component, and performs all pairwise minute-overlap checks.

Aggregate result:

- 9 distinct course codes.
- 15 component records and 31 total credits.
- 14 scheduled weekday components and one unscheduled online `NIL` component.
- 35 resolved weekly intervals.
- 1,742 exact contact minutes and 29 explicit sessions.
- 0 unresolved physical components and 0 clash pairs.

A recorded theory/lab registration is evidence only for that particular registration. It does not establish a universal faculty-pairing rule, and no pairing rule was created from the private file.

## Verification and remaining limitation

The completed verification run produced:

- 101 passing Pytest tests, including 17 Fall-calendar integration tests.
- Passing Ruff lint and format checks, strict Mypy, and `pip check`.
- A successful aggregate-only private-reference validation with the counts above.
- A localhost browser import through validate, preview, commit and semester activation.
- Browser resolution of `L49+L50` with its exact Thursday times and shared `THU-PM-1` session, and `A1+TA1` with readable Monday/Wednesday/Friday labels.
- Browser conflict results of `confirmed_clash` for `A1`/`L14` and `no_clash` for `A1`/`A2`, with no console errors.

The browser check also covered the coexistence of independently active calendars for different semesters. The inspector selects the first active profile deterministically on initial load and preserves the newly committed profile after commit, rather than allowing a later active profile for another semester to overwrite the selection. Static JavaScript is versioned in the HTML so this behavior is not masked by a stale browser cache. The synthetic Phase 2 fixture remains independent and continues to pass its own tests.

The profile can become `official_verified` only after an authentic institutional timetable document is retained as reviewable evidence and reviewed with a recorded reviewer/time. Phase 2.1 does not start the cross-course optimizer or any registration automation.
