# Privacy, integrity, licences and distribution

## VTOP

The saved VTOP HTML contains a student identifier and a CSRF token in script/form markup. Those are not course-allocation data. **Never copy raw screenshots/HTML to the new repository**, logs or generated JSON. Use a strict allowlist of table columns and selected dropdown text; check git history and test fixtures for tokens/session IDs. Do not intercept cookies or perform hidden requests.

Run Tampermonkey within the signed-in browser by user intent. Do not auto-register, scrape seat counts from unsupported endpoints or try to bypass portal throttling. Use an optional manual `Capture Current Course` button as fail-safe. Avoid perpetual polling, hidden fetches, or high-volume automated dropdown cycles.

## Offline privacy

Student schedules, grades and course preferences remain on local disk. Provide export/backup buttons and opt-in deletion. Optional diagnostics redact student identifiers, notes and faculty preferences if shared. Do not include analytics calls, auto-update checks or external fonts in initial build.

## Third-party software

- Upstream `CodeChefVIT/ffcs` repository, reviewed in connected GitHub, has an **MIT license** and Next.js/React stack. Retain its MIT notice and attribution if copying substantial code; format compatibility alone does not imply code copying.
- Bundled file `SHEPHERD_LICENSE_AGPL-3.0.md` describes Shepherd.js AGPL-3.0/commercial terms; **do not bundle Shepherd.js**. Prefer simple accessible self-authored browser onboarding; review authoritative licences if a new dependency is proposed.
- FastAPI/Uvicorn/Jinja2 and any spreadsheet/solver/packaging dependency require a distribution-time licence review. Choose dependencies and bundled binaries consistent with the intended private/public distribution.
- Avoid copying copyrighted assets/logos from the upstream website into an unrelated app; use self-made neutral icons and text.

## Local HTTP security

Bind to `127.0.0.1` by default; no public or LAN binding unless explicitly requested. Validate the HTTP `Host` header (localhost/127.0.0.1 plus configured port) to mitigate DNS rebinding. Treat untrusted web content as hostile; validate Origin on write requests, use CSRF protection where applicable, and never enable permissive wildcard CORS. Limit upload sizes and enforce allowed media types. Do not expose arbitrary filesystem paths, database exports or debugging tracebacks through the HTTP API. No CDN scripts/fonts, analytics or internet access during normal usage. User data and sessions remain on the laptop; a browser tab talking to localhost does not imply cloud use.

## Software integrity

Use migrations, provenance, cryptographic checksum for imported documents, backup and restore. A bad import must not replace the live planner database without an explicit confirm and rollback path. Don't treat mutable external files as trusted executable code; no `eval`, code injection or loadable Python modules from user data.
