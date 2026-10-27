# Product requirements

## North-star user flows

**Capture:** visit VTOP course allocation page → select a category and subject → Tampermonkey captures displayed rows → repeat → export one versioned JSON for all captured subjects; the local website imports it with a summary of imported/missing/duplicate/changed records. CSV and polished Excel are secondary exports from the same local database.

**Plan next FFCS:** open semester offering snapshot → mark must-take/strong preference/optional/avoid → set faculty acceptable/preferred/blocked → set minimum/target/maximum credits and existing commitments → choose scheduling preferences (minimize physical lab blocks, reduce days/hours on campus, avoid long gaps, morning/evening preference) → generate ranked valid plans → compare timetable cards → lock selections → recompute alternatives incrementally → save/print/export.

**Choose minimal-lab courses:** browse available subjects with curriculum category, course type, credits, expected in-person class sessions, required labs and project component separated; visualize how choosing TH or ETP instead of ETL changes the candidate workload and progress toward category requirements. Never imply ETP has zero work: it may carry project deliverables.

**During FFCS:** enter seat availability manually, pin registered sections, blacklist full sections → show still-feasible alternatives and small, actionable recovery steps (swap faculty, change section, drop optional course). Do not automatically query live seat availability or submit registrations.

**Degree plan:** load curriculum + completed records + per-semester plans → show earned, planned and remaining by category and semester → verify mutual exclusions, prerequisites, caps and remaining courses → recommend eligible courses *only from separately known offerings* → transfer semester courses to timetable search.

## Must-have functional requirements

- FR-01 Import versioned VTOP JSON, typed CSV, prior workbook, legacy saved degree JSON, and optional FFCSinator TypeScript records through explicit adapters.
- FR-02 Preserve **every** source allocation row including slot, room, faculty, component type, source order/page/timestamp and source semester; show review of malformed rows.
- FR-03 Distinguish `course`, `offering`, `component`, `section`, `candidate registration`, `timetable`, `plan` and `degree record` as separate entities.
- FR-04 Verify time clashes at minute precision against a versioned campus calendar, not just string overlap.
- FR-05 Model ETL with all required ETH/ELA components; ETP with ETH/EPJ association and no invented lab; TH theory only; handle LO, ELJ and other configured types.
- FR-06 Support optional faculty coupling and explicit faculty pairing restrictions; unknown pairing produces a review warning.
- FR-07 Generate exact viable solutions for requested required courses, or prove none under the configured hard constraints; support course-set search when electives optional.
- FR-08 Rank results deterministically, report **why** they score as they do, honor user-set course priority, and avoid recommending forbidden/blocked options.
- FR-09 Count solutions accurately without constructing all combinations, display top-K incrementally and allow cancellation.
- FR-10 Degree progress: course requirements, earned/ongoing/planned, credit bands, category quotas, prerequisites, exemptions, equivalencies, anti-double-count, alternative codes.
- FR-11 Create and compare named planning scenarios, lock/freeze partial schedules, maintain undo/redo for mutable planning operations, restore after local server restart.
- FR-12 Export canonical JSON, CSV, category-separated Excel, readable timetable PDF/image **when an export dependency is configured**, and optional FFCSinator compatibility format.
- FR-13 Detect changes between capture snapshots (new/removed/changed section); never quietly merge offerings from different semesters.
- FR-14 No persistent internet requirement, account or AI inference for core features.
- FR-15 Explain unsatisfiable scenarios with a minimal or short human-readable set of conflicting constraints where feasible, and suggested relaxations without silently applying them.
- FR-16 Import safeguards: dry-run summary, reversible transaction and backup before migration.
- FR-17 Fast accessible keyboard/mouse navigation, search, bulk faculty preference controls and consistent visual state.

## Non-functional requirements / budgets (initial design targets, not measured claims)

- NFR-01 Remain responsive on typical Windows 11 laptop, even if hypothetical assignment count exceeds hundreds of millions.
- NFR-02 Keep search, sort and timetable viewing interactive; run the solver in a cancellable background **worker process/task controlled by the local Python server**, with progress and cancellation through HTTP/SSE; progressively return top-K results.
- NFR-03 For baseline ~27 courses / ~181 allocation rows, target import validation <2 seconds on a reference laptop; under a configurable 5-second first-results budget for typical 8-course requests. Benchmark and refine, not guaranteed.
- NFR-04 Memory growth bounded by active search state / top-K and caches, not total number of schedules.
- NFR-05 All saved records versioned with migrations and deterministic backup/restore.
- NFR-06 No hardcoded school list, department, batch, category target, course aliases or slot tables in main UI logic.
- NFR-07 WCAG-minded text contrast, visible focus, keyboard navigation, non-color-only status, min 44px hit targets where possible.
- NFR-08 Local exception logging with redaction of authentication details and optional diagnostic export.

## Deliberate distinctions

- **Hard:** no timetable overlap, valid section pairs, must-take courses, formal credit ceiling, explicit exclusion, real prerequisites when known.
- **Soft:** fewer lab blocks, fewer days/hours on campus, individual course rankings, good faculty, morning/evening choice, consecutive classes, shorter gaps.
- **Unknown:** VTOP availability may not show seats, an EPJ row may not tell weekly project workload, and the curriculum type may not be visible on an allocation page. Do not pretend to know these.
