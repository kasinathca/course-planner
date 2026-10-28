# Phase 5 — degree planning, migration, and FFCS recovery

## Release scope

Phase 5 is implemented as FFCS Studio 0.6.0 on top of the verified Phase 4 baseline `d30b50f3b338274095e94961e016b4fc67665f69`. It adds a source-aware degree domain, schema migration 0004, curriculum and legacy imports, versioned ten-semester plans, deterministic recommendations, Phase 4 scenario transfer, manual allocation states, and exact minimum-disruption recovery. It does not add VTOP polling, registration submission, a cloud service, Node, or a new frontend framework.

## Curriculum and programme model

`ffcs_studio.degree.models` defines typed programme policies, category requirements, catalogue courses, source-backed course relationships, prerequisites, academic record statuses, and plan documents. Catalogue identity and semester offering identity are deliberately different. Each catalogue record retains a stable canonical identity, original source identity, code/title/category/type, exact milli-credits when known, L/T/P/J values when supplied, provenance, alternative group, notes, and unresolved fields.

The seeded programme policy is scoped to VIT Vellore Integrated M.Tech CSE (Data Science), admission 2024–25. It records PC 81, PE 48, UC 61, UE 12, SPE 18, BC 0, NC 5, and displayed total 225. These are not universal VIT rules. NC remains `pending_classification`: its five recorded units remain visible, while confirmed credit-bearing units and graduation inclusion stay unknown. The application therefore makes no official graduation-complete claim.

## Exact accounting and semester plans

`degree.accounting` parses decimal credit inputs once into integer milli-credits. It keeps earned, enrolled, planned, and unknown progress separate; calculates category and semester/cumulative totals; reports projected remaining and category surplus; applies configurable warning thresholds without inventing a hard 27-credit cap; and identifies the semester causing a warning. Completed equivalent alternatives and repeat attempts do not satisfy the same requirement twice. Failed, withdrawn, tentative, and future-planned records never become earned credit.

Plans support semesters 1–10. Historical completed records with no trustworthy term use semester 0 (`Term unknown`) rather than a fabricated semester. Every edit appends a plan revision; stale expected revisions return a conflict. Restore creates a new revision, while duplicate and archive preserve the original history.

## Relationships and prerequisites

Relationship records support equivalent, mutually exclusive, basket, same-requirement, same-code-distinct-record, prerequisite, and review-required semantics. Distinct STS3022 source identities remain distinct even when their displayed codes match. Requirement keys prevent equivalent alternatives from double-counting.

The prerequisite evaluator supports verified AND requirements, OR groups, minimum semester, explicit waivers, and unknown evidence. It never infers prerequisites from course numbering or titles. The missing private curriculum evidence for the English alternatives, ENG1902/ENG1903, GER1001, and EXC1072 was not invented; those exact institutional relationships remain pending reviewed source import.

## Curriculum and legacy migration

The canonical contract is `schemas/curriculum-catalog-v1.schema.json`, also packaged under application resources. Import follows validate → preview → explicit commit and retains source JSON, digest, filename, provenance, original order, and warnings. A repeated canonical digest is idempotent.

The version-6 legacy adapter validates `version`, `catalog`, `completed`, `plan`, `settings`, `offerings`, and `updatedAt`; resolves plans using original `courseId`; rejects unknown references; retains duplicate-looking catalogue records; stores every snapshot separately; and compares additions, removals, moved semesters, and status changes. Activation is an explicit named-timeline operation. It never unions divergent plans and never promotes historical `offerings` metadata to current VTOP availability.

`examples/synthetic_curriculum_phase5.json` is conspicuously synthetic. It contains six courses, two distinct same-code STS3022 alternatives, an unknown-credit record, and a verified synthetic prerequisite. No real student completion, registration, or private portal data is present.

## Persistence migration

Additive migration `0004_degree_planning.sql` creates normalized programme, curriculum, category, catalogue, relationship, prerequisite, import snapshot, degree plan/revision/entry, degree-scenario link, registration availability history, recovery run, and recovery decision tables. Migrations 0001–0003 are unchanged. Foreign keys and indexes protect identities and query paths. Existing schema-3 databases are backed up before upgrade, and regression tests confirm prior imports, calendars, scenarios, and results remain present.

## Timetable integration

A degree-plan semester is transferred through a preview and commit service into the existing Phase 4 scenario document/API. The transfer retains degree-plan revision, programme/curriculum identity, semester, credits, roles, calendar, exact offering revision, and allocation source. Matching is by reviewed course/offering identity in the selected campus and semester—not by title and not across semesters. Missing offerings, calendar mismatch, or incomplete component/pairing evidence block transfer. The existing solver remains authoritative for feasibility.

## Recommendations

Recommendations are deterministic and explain the remaining category that caused each result. Completed/planned/equivalent courses are excluded appropriately, verified hard prerequisites are enforced, and unknown prerequisites remain unknown. A catalogue-only future recommendation is explicitly `Tentative only · offering unknown`; it is not ranked as a currently selectable section. Where verified candidates exist, physical lab workload and scheduleability remain available to the existing solver/ranking path.

## Manual availability and FFCS recovery

Manual states (`available`, `full`, `unavailable`, `registered`, `registration_failed`, `waitlisted`, `pending`, `unknown`) are scoped to campus, semester label, offering revision, exact allocation ID, timestamp, provenance, and note. Updating a state clears the prior current row but retains history. States never move silently to a new revision and are never presented as live VTOP evidence.

Recovery uses exact candidate/allocation identities and a lexicographic objective:

1. keep registered components immutable unless explicitly unlocked;
2. preserve must-take courses;
3. reject blocked allocations;
4. minimize assignment changes;
5. minimize faculty changes;
6. minimize slot changes;
7. preserve higher-priority optional courses;
8. minimize added physical lab sessions;
9. apply the ordinary stable ranking tie-break.

Meeting overlap remains a hard feasibility check. The search proves the minimum when it exhausts the bounded reference space; hitting a node limit or cancellation returns `best found so far`. Independent small reference tests cover a valid replacement, impossible locks, same-faculty distinct sections, exact meeting clashes, and resource-limited labeling. Saved-scenario recovery builds options from the real Phase 3 candidate service, respects revision-scoped manual states, and persists the selected evidence and assumptions. Expensive recovery requests can run in bounded spawned worker processes with cooperative/forced cancellation and shutdown.

## API and browser workspace

Versioned endpoints cover programme/curriculum list/detail, curriculum/legacy validate-preview-commit, legacy compare/activate, paginated catalogue search, plan CRUD/revisions/restore/duplicate/archive/compare, progress, recommendations, semester transfer, manual availability, direct recovery, saved-scenario recovery, and recovery jobs/status/cancel. FastAPI request models reject extra fields. Existing Host, Origin, CSRF, JSON, and request-size protections apply to writes.

The Degree Planner browser destination now includes programme totals, category rows and warnings, compact catalogue search, a ten-semester matrix, add/move/status/remove actions, named revisions, canonical/legacy import controls, recommendations, manual allocation history, scenario transfer, and recovery output. It uses the existing local ES modules and semantic native controls.

## Verification

The final automated suite contains **156 passing tests** (the verified Phase 4 suite plus Phase 5 domain, persistence, API/integration, and worker coverage). Final gates:

- `pytest`: 156 passed.
- `ruff check .`: passed.
- `ruff format --check .`: 116 files formatted.
- `mypy src`: no issues in 65 source files.
- `pip check`: no broken requirements.
- Fresh schema: version 4.
- Populated schema-3 upgrade: passed with backup and preserved data.
- Installed wheel: version 0.6.0; all four migrations, canonical curriculum schema, template, and Degree Planner module present.

The public synthetic benchmark (`tools/benchmark_phase5.py`, Windows 11/Python 3.12, this verification run) reported median/max:

| Operation | Median | Max |
| --- | ---: | ---: |
| 101-course, 75-record accounting | 0.215 ms | 0.505 ms |
| 101-course catalogue filtering | 0.007 ms | 0.011 ms |
| 7-course × 4-option exact recovery | 22.858 ms | 26.085 ms |

The browser acceptance pass exercised localhost startup, synthetic curriculum file selection/validation/preview, target and NC-warning rendering, catalogue search data, semester 5/6 additions, a move from semester 6 to 7, immediate unsaved progress recomputation, per-semester PE contribution, completed versus planned accounting (4 earned and 3.5 planned), course-note save/reload, three saved revisions, revision 1-versus-3 comparison, deterministic recommendations, an exact recovery that replaced blocked `a-1` with `a-2` while preserving registered `course-b`, server restart/reopen, and clean worker shutdown. A fresh diagnostics tab reported no console warnings or errors. The Degree Planner had no page-level horizontal overflow at 390×844 or 768×900. The in-app acceptance browser does not implement JavaScript prompt/confirm dialogs, and the available Chrome extension had local-file upload permission disabled; therefore the single automated browser session could not combine file upload with the final native confirm click. Atomic commit, duplicate-timeline, restore, timetable transfer/solver, availability history, CSRF, and saved-scenario recovery are covered through the same localhost services in API integration tests.

## Private-source status and security review

The consolidated curriculum Markdown and five historical JSON snapshots named by `reference/source_manifest.json` were not present in the documented project/private locations. No arbitrary private-directory search was performed. Consequently, the actual 101-course catalogue and 35 completion records were **not** migrated and are not claimed. They can be imported later through the reviewed local workflow without changing schema 4.

The publish set was checked for credentials, tokens, raw VTOP HTML, student identifiers, private snapshots, SQLite databases, virtual environments, caches, build outputs, `node_modules`, and `.next`. Source JSON parsing uses strict typed/schema validation; no `eval`, arbitrary path API, remote request, portal polling, or registration automation was added.

## Known limitations and Phase 6 readiness

- Real curriculum/course relationships, prerequisites, completions, and five-snapshot chronology remain pending the exact private sources.
- NC accounting, the official semester maximum, and several institutional equivalency/exclusion rules remain unresolved and visible.
- Manual availability is local evidence, not live seat availability.
- Catalogue-only recommendations remain tentative until a matching semester offering is imported.
- Direct recovery accepts a reviewed structured payload; the saved-scenario endpoint is the safer source-derived route for real work.
- Recovery job state is in-memory and is invalidated on server restart, while completed decisions remain persisted.

Phase 5 is ready for independent review. Phase 6 is intentionally not started.
