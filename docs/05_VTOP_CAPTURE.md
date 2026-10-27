# VTOP Tampermonkey collector — behavior specification

## Observed DOM and dynamic path

On three local saved VTOP pages, category select is `select#curriculumCategory`, course select is `select#courseId`, course list container is `#courseListFragement` and allocation table is within `#courseDetailFragement`; note exact **misspelling** `Fragement`. VTOP's own change callbacks asynchronously replace these fragments. Both captured pages contained **nested duplicate IDs** for the fragments. Therefore do not rely on single-element ID uniqueness.

The visible allocation table has four columns **Slot Detail, Venue, Faculty, Course Type**. Two sampled courses: CSI3002 (ETH + ELA) and MDI3002 (TH), cross-identified by their matching rows in the supplied winter PDF. Crucially, saved HTML `option[selected]` remains on `-- Choose --` despite the dynamically loaded table; the **live script must read DOM `.value` while user is interacting**, and any import of static captures must ask for identity when not recoverable. User-selected categories/courses and semester label can be read from current page. Some rows have `NIL` venue and course types `EPJ`.

## Collector behavior

1. Script loads only on explicitly permitted VTOP academic allocation URL(s), with `@grant GM_getValue / GM_setValue / GM_download` if used and no third-party network permissions.
2. On page load, locate visible category and course selectors and their **current selected** values; do not try guessing course identity from prior clicks.
3. Observe only a stable parent of the dynamically replaced course-detail container, reattach if its node is replaced; small debounced callback after mutation, not a global per-frame observer or permanent polling.
4. On mutation/change, parse the **currently visible table whose normalized headers match the four expected columns**; snapshot category/course/semester before and after parsing, discard if they changed mid-update; reject stale intermediate table.
5. Capture all rows in DOM order, including duplicates, mixed ETH/ELA/EPJ and multi-slot lab combinations. Normalize whitespace only; preserve raw text strings, original row ordinal and table schema.
6. Keep data under `(semester, category, course code)`, replace a course's rows when a newer complete capture arrives, preserve each prior snapshot for diff. Never append results from another course accidentally.
7. Show discreet status: `12 / 27 courses captured`, most recent course, source timestamp, error count. User actions: **Capture this subject**, **Export JSON**, **Export CSV**, **Reset semester capture**, **Review incomplete**.
8. A one-click 'Capture currently loaded' button works even if mutation detection fails. Optional guided next-course navigation may be added later, **only using ordinary UI events, slowly and serially**, provided the portal permits it; manual category/course clicks are the v1 contract.
9. All processing local in the userscript, no broad site API crawling, no background authenticated fetch requests, no database scraping, no shared credentials, no forced refresh loops.
10. JSON output contains schema version, capture metadata, offered subjects and per-row raw details; credential-free, deterministic and validated by the local Python web application. CSV flattening is a secondary lossless raw-allocation export with semester/category/course columns.

## Parser correctness checks

- Missing select, nonselected course or empty table -> no silent 'success'.
- Loading/intermediate table -> require stable category/course identity and header verification.
- Unknown header columns -> preserve extras and flag for manual review, do not drop.
- Duplicate fragment IDs -> locate descendants by structure/content, not only `.getElementById`.
- Reactivity -> avoid 100ms polling, `document.body` full subtree every change and CPU-heavy equality checks.
- Semester migration -> separate export file and local state namespace.
- Unexpected VTOP redesign -> disable capture safely and offer DOM diagnostics (tag names/headers only, not full session HTML).

## Security

Never include hidden fields, auth cookie, CSRF token, student registration number, generic page HTML, or script snippets in export or console logs. Use an explicit JSON allowlist. Avoid writing to server, altering `window.fetch`/`XMLHttpRequest`, leaking internal endpoint URLs, or interfering with website behavior.

## Offline fallback

The localhost website accepts legacy workbook or a hand-entered allocation table; AI/PDF extraction only used when deterministic import fails and reviewed by user.
