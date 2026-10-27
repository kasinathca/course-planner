# Phase 0 repository and specification audit

Audit date: 2026-10-28. This records the initial state before Phase 0 implementation and the safe disposition of gaps. It does not claim that unresolved university policy is verified.

## Initial repository state

- The directory contained the v0.2 documentation dossier, three JSON schemas, four sanitized examples, one source manifest, and `tools/inspect_capture.py`. It contained no application package, tests, startup script, virtual environment, SQLite database, Node project, or private source archives.
- The directory was **not a Git working tree**: `git status`, `git remote -v`, and `git log` all reported that no `.git` repository exists. Consequently, no uncommitted Git changes or configured remote could be inspected. The supplied GitHub URL was not cloned or pushed.
- The system `python` is 3.10.11 and does not satisfy the approved Python 3.12+ baseline. A local Codex-provided Python 3.12.14 runtime was available to create the ignored project `.venv`.
- No obsolete PySide6, Qt, Electron, React, Next.js, Node, npm, or CDN implementation was present. The only references describe them as prohibited or historical.

## Specification gaps and conflicts

- `docs/04_DATA_MODEL.md` refers to `schemas/degree-snapshot.schema.json`, but that file was not supplied. The existing `legacy-degree-v6-minimal.schema.json` is only a permissive migration envelope. A canonical degree schema is deferred until the degree contract is designed in its proper phase; inventing it in Phase 0 would risk false requirements.
- `docs/11_TEST_AND_ACCEPTANCE.md` calls for three sanitized saved-VTOP states, including a no-subject state. Only the theory-only and ETH+ELA JSON fixtures were supplied. Empty/no-selection collector behavior belongs to the later userscript phase; Phase 0 validation covers both supplied canonical exports.
- A project licence decision and top-level licence file were not supplied. Phase 0 declares the package licence decision pending and copies no legacy or third-party application code.
- The source manifest describes private/provenance inputs that are intentionally absent. They were not reconstructed or downloaded. Migration parity for five degree snapshots, the historical workbook, and FFCSinator TypeScript remains deferred to their documented phases.

## Unverified institutional rules

The open questions in `docs/15_OPEN_QUESTIONS.md` remain authoritative. In particular, Phase 0 does not certify slot times, ETH/ELA faculty pairing, opposite-shift rules, EPJ contact time, NC credit accounting, the semester credit cap, prerequisites, or equivalencies. Domain models retain raw types and unknown component values for review. No solver, pairing engine, or official timetable claim is implemented.

## Phase 0 migration safeguards

- Raw VTOP allocation rows are immutable domain records with their original ordinal and exact field values; normalized component classification is additive.
- Unknown component values validate as source data, generate a review warning, and round-trip unchanged.
- Semester offerings remain distinct from curriculum courses. No cross-semester merge, faculty normalization, component pairing, or slot-time inference occurs.
- `.gitignore` excludes local virtual environments, databases, private directories, archives, `node_modules`, and `.next` output. Static website templates remain trackable.
