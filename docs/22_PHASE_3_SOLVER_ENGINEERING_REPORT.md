# Phase 3 solver engineering report

Phase 3 implements an exact, source-aware timetable solver for the existing local FastAPI application. It uses imported SQLite offerings and one exact immutable calendar version; it does not infer faculty, component pairings, credits, curriculum types, or official slot times. The release version is 0.4.0.

## Architecture and completeness

`ffcs_studio.solver` has no FastAPI or browser dependency. Immutable `ScenarioSnapshot`, `CoursePlan`, `SolverCandidate`, `SolverInterval`, constraint, result, and outcome dataclasses are the worker boundary. The service layer resolves active offering revisions and every retained source allocation into that representation. A SHA-256 fingerprint covers campus, semester, calendar ID, offering/revision identity, filtered candidate identities, metadata and sources, locks/exclusions, occupied periods, credit constraints, ranking preferences, pairing policy, budgets, and assumptions.

`CompleteCandidateSource` is intentionally separate from the bounded one-course preview API. The browser preview can say `truncated`; the solver source never uses that display limit. It resolves every applicable allocation through the chosen calendar, applies saved pairing evidence and explicitly enabled provisional rules, preserves offering/revision/allocation identities, and rejects unknown physical timing. Four-slot labs are retained. Verified duplicate ETH/EPJ teaching intervals are deduplicated as physical meetings; `NIL` project evidence adds no invented occupancy.

The optimized search orders required courses first and then applies MRV, priority, and stable course ordering. It propagates locked allocation/faculty and forbidden allocation/faculty restrictions before search, uses a 10,080-bit weekly occupancy integer for constant-time clashes, prunes impossible remaining-credit bounds, and maintains only the best K results. Every leaf is independently revalidated for required/excluded courses, occupied periods, pairwise half-open interval overlap, and credit/category constraints. Exhaustive, infeasible, cancelled, resource-limited, unresolved, and failed outcomes remain distinct; a partial search is never labeled exhaustive.

The independent reference solver deliberately enumerates tiny assignments without importing the optimized pruning logic. Deterministically seeded randomized cases compare the exact feasible result-identity set and exact count against the optimized engine.

## Exact time and academic semantics

The occupancy model assigns one bit per minute for seven days. Intervals are half-open: `[08:00, 08:50)` and `[08:50, 09:40)` do not clash, while a one-minute overlap does. Unit tests compare bit intersections with direct interval predicates at boundaries. Candidate construction also checks clashes inside a complete multi-component option before cross-course search.

Strict mode requires an officially verified calendar, verified curriculum metadata, verified credit metadata whenever credits constrain feasibility, and evidence-supported component pairings. The bundled Fall calendar remains `user_supplied`; it is suitable only for explicitly approved exploratory work. Exploratory results are labeled as such and carry all calendar, metadata, and pairing assumptions. Campus and semester must match exactly for every offering and the selected calendar, preventing silent Fall/Winter mixing.

Credits are integer milli-credits. Unknown credits are permitted only when no credit constraint depends on them; no total is invented. Results expose per-course credit and curriculum values with source status, exact meetings, allocation identities, faculty, venue, total credits where known, physical lab sessions/minutes, contact minutes, campus days, daily start/end spans, occupied spans, gaps, late minutes, preferred-faculty hits, a lexicographic ranking vector, explanation, evidence status, assumptions, and stable result identity.

## Ranking and counting

Ranking is deterministic and does not change feasibility. It compares optional-course inclusion by ascending priority tier before credit-target distance and workload preferences, followed by physical lab sessions, lab minutes, campus days, daily span, gaps, requested theory window, preferred-faculty hits, and a stable assignment key. A preference can never remove a required course or relax a hard restriction. Result IDs depend on the calendar plus revision/candidate identities, not ranking configuration.

Exact counting is a separate worker operation. Its memo key contains the remaining course index, weekly occupancy, accumulated credits, and per-category credits. Optional-course omission is a distinct branch. Only a successfully exhausted count returns a number; cancelled, resource-limited, and failed counts return no purported exact value. Top-K length is never presented as the number of possible schedules.

## Worker lifecycle and API

`SolverJobManager` uses the Windows `spawn` multiprocessing context with a configurable bounded worker count (default 2, range 1–4). Search and count have independent cooperative events, bounded progress queues, and a termination fallback after the configured grace period. Jobs transition through queued/running/completed terminal states, cancellation is real process interruption, result storage is bounded by K, API pagination is bounded to 50 items, shutdown signals and joins every worker, and stale completed jobs are capped.

The localhost API adds:

- `POST /api/v1/solver/scenarios/validate`
- `POST /api/v1/solver/jobs`
- `GET /api/v1/solver/jobs/{job_id}`
- `GET /api/v1/solver/jobs/{job_id}/results`
- `POST /api/v1/solver/jobs/{job_id}/cancel`
- `POST /api/v1/solver/jobs/{job_id}/count`
- `GET /api/v1/solver/jobs/{job_id}/count`
- `POST /api/v1/solver/jobs/{job_id}/count/cancel`

The existing loopback binding, Host allow-list, same-origin/CSRF enforcement, request-size limit, no-store policy, and structured JSON errors still apply. CPU enumeration never runs on the FastAPI event loop. Jobs are intentionally in memory and become invalid after server restart; scenario fingerprints make their source snapshot auditable. Phase 3 requires no database migration, so the existing version-2 SQLite schema and stored user records are untouched.

## Browser interface

The functional intermediate planner lets the user select an imported campus/semester and exact matching calendar, load every page of active offerings, assign required/optional/excluded roles, provide reviewed type/credit metadata, set priority tiers, lock allocations/faculty, forbid allocations/faculty, add occupied periods, set credit bounds/target, configure faculty/time/lab/day preferences, and explicitly authorize exploratory assumptions. It validates scenarios, polls process progress, cancels search, displays bounded ranked meeting tables, and requests/cancels exact count. This is intentionally not the full Phase 4 workspace or persistence/export design.

## Benchmark

`tools/benchmark_phase3_solver.py` is reproducible and contains no private course or registration data. It loads the actual public `examples/fall_2026-27_weekday_slot_calendar_USER_SUPPLIED.json`, selects non-overlapping real calendar intervals, and assigns them to conspicuously synthetic courses. Measurements below were recorded on 2026-10-28 with Windows 11 build 26300, Python 3.12.14, a 12-logical-processor Intel64 Family 6 Model 151 CPU, 25,463,480,320 bytes total physical memory, and 13,127,634,944 bytes available at measurement time.

| Measurement | Exhaustive case |
|---|---:|
| Selected courses | 8 required synthetic courses |
| Available section candidates | 64 |
| Naive assignment product | 16,777,216 |
| Nodes visited | 554,248 |
| Conflict branches pruned | 444,648 |
| Feasible assignments | 40,320 |
| Top-K retained | 20 |
| Time to first result | 0.00065 s |
| Time to first 20 | 0.01026 s |
| Exhaustive search time | 20.3743 s under `tracemalloc` |
| Peak traced Python memory | 768,240 bytes |
| Exact count | 40,320 (`exact`) |
| Count nodes / pruned | 2,040 / 1,016 |
| Count duration | 0.00172 s |

The search timing includes `tracemalloc` overhead and top-K ranking construction; the count benefits from memoized symmetric occupancy states. A second scenario used 15 required synthetic courses and 225 candidates. After progress reached 7,455 nodes, the process-backed search cancelled in 0.00809 seconds; shutdown left zero `ffcs-*` worker processes. These figures are implementation evidence, not a performance promise. The historical approximate 469-million figure belongs to different unknown inputs and is not reproduced or claimed here.

## Verification

The final suite contains 125 tests. Coverage includes Phase 0–2 regression behavior; exact minute boundaries; complete versus truncated candidate sources; explicit/provisional/unknown pairing; four-slot labs and EPJ deduplication; required/optional/excluded courses; credit and occupied-period constraints; ranking stability; independent randomized reference equivalence; exact count semantics; actual search/count cancellation; bounded concurrency; full SQLite-to-API result/count flow; locked faculty; semester isolation; and CSRF.

Release checks performed:

- `python -m pytest`: 125 passed.
- `python -m ruff check .`: passed.
- `python -m ruff format --check .`: passed.
- strict `python -m mypy src`: passed.
- `python -m pip check`: no broken requirements.
- `scripts/start.ps1 -Port 8879 -NoBrowser`: version 0.4.0 health response and clean Ctrl+C child shutdown.
- Real Chrome localhost flow on isolated SQLite: 2 offerings, 3 complete options, exhaustive 3-result search, exact count 3, visible assumptions/provenance/meetings, no browser console warnings or errors.
- Existing version-2 migration-preservation tests pass; no Phase 3 migration exists.

## Known limitations and Phase 4 readiness

- The repository still has no independently reviewed official institutional timetable. Strict verified mode therefore remains unavailable for the bundled Fall calendar.
- Credits and curriculum types are not imported by the current VTOP capture contract; users must provide reviewed metadata, and exploratory provenance remains visible.
- Candidate pairing completeness depends on saved evidence or explicitly enabled assumptions. The system refuses to invent missing pairings in strict mode.
- Search ordering and remaining-credit/conflict pruning are exact, but there is no ranking-specific admissible branch-and-bound. Large exhaustive searches can reach their explicit node budget; partial results are labeled best found so far.
- Job state and unsaved planner inputs are in memory and do not survive a server restart. Saved scenarios, comparison, export, responsive workspace polish, and accessibility refinement belong to Phase 4.
- Infeasibility diagnostics identify the affected course/restriction class but do not yet compute a minimum unsatisfiable course core.

The solver/API boundary and functional browser controls are ready for Phase 4 to add persistent scenario management, comparison and export without changing exact feasibility or count semantics.
