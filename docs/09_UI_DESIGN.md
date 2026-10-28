# UI design and interaction — local browser edition

## Design direction

The final interface is a **website served locally in the user's normal browser**, not an installable desktop GUI. Use semantic HTML, CSS variables, responsive layout, accessible forms and tables, and modern vanilla JavaScript ES modules. Do not introduce React, Node, a bundler, CDN assets, remote fonts, or heavy client frameworks. Server-render initial pages using Jinja2 if useful and update portions of the UI through small documented local JSON endpoints. Keep all application state authoritative in the Python services/database. Suitable for Chrome or Edge on Windows 11, without external network access.

Inspired by restrained Microsoft Fluent 2 / Google Material principles, not copied branding. Light theme by default; optional dark mode using local CSS tokens. No huge KPI strip, overdesigned hero cards, gratuitous gradients, tiny type or excessive counters.

## Navigation — at most five persistent destinations

1. **Overview** — semester, selected scenario, minimal degree-progress headline and next action.
2. **Courses & Data** — current offerings, faculty rows, rooms, source/provenance and import preview.
3. **Timetable Planner** — three-zone workspace: **left** course priorities and locks, **center** interactive weekly timetable, **right** ranked alternatives and why-this-plan explanations.
4. **Degree Planner** — category progress, semester allocations and requirement warnings.
5. **Scenarios** — save/compare/restore, audit, settings and import/export.

Manual availability/registration recovery lives within the timetable planner; never automate VTOP registration.

## Typical planning view

```text
┌ FFCS Studio | Winter 2026–27     [Import] [Scenarios] [Settings] ┐
│ Overview | Courses & Data | Timetable Planner | Degree | Scenarios│
├───────────────────────────────────────────────────────────────────┤
│ Course selection   │ Real timetable         │ Best valid options    │
│ mandatory/priority │ Mon–Fri, exact times   │ #1 fewer lab blocks  │
│ locked faculty     │ component differences  │ #2 fewer campus days │
│ credit constraints │ highlight conflicts    │ compare / explain    │
├───────────────────────────────────────────────────────────────────┤
│ Credits / lab blocks / days                  [Generate] [Save]   │
└───────────────────────────────────────────────────────────────────┘
```

## Design tokens and layout

- At 1280×720 ensure all critical controls remain visible and panels can scroll independently; smaller displays collapse into tabs or drawers, never overlapping.
- Typical body 14–16 CSS px; page titles 20–24; input/control height at least 40–44 px; spacing follows an 8 px grid.
- Use neutral background `#F7F8FA`, surface `#FFFFFF`, text `#202124`, border `#DDE2E8`, one primary accent e.g. `#2563EB` and semantic warning/success/danger only where meaningful.
- Long faculty names, venue IDs and composite slots must remain readable. Prefer accessible native HTML tables with sorting/filtering and paginated or virtualized large result sets.
- Focus outlines, keyboard navigation, visible labels, status text independent of color and WCAG-minded contrast. No inaccessible drag-only interactions.
- Progressive disclosure for advanced solver counts and detailed ranking weights; course search and hard constraints always easy to find.
- Timetable may horizontally scroll where needed; preserve locked selections and scenario state on refresh.
- Avoid rendering all possible timetables; fetch and display top-K and paginated results.

## Required interaction states

Import: upload file → validate → preview errors / duplicates / differences → commit/rollback. Never auto-merge semester snapshots.

Course detail: source allocation rows, derived registration choices, curriculum, user preferences. Distinguish official source facts from inferred/unknown fields.

Timetable: generate → stream/poll progress → cancel → compare two or three → lock selections → recompute → save/restore. Never block the browser event loop with millions of combinations.

Recovery: show locked registrations, newly unavailable sections, minimal actionable alternatives and explicit apply confirmation.

Empty/error/loading states must tell the user how to proceed and preserve unaffected work.

## Phase 4 implementation note

Version 0.5.0 implements this shell with Overview, Courses & Data, Timetable Planner, an explicitly upcoming Degree Planner, and Scenarios. The planner uses independent scrolling zones at desktop width and collapses to a single column without horizontal overflow on narrow viewports. Exact meeting intervals are rendered as focusable buttons plus a semantic table. Scenario and result save flows use labeled native dialogs; archive/delete remain explicit; the keyboard skip link preserves the current route. See `23_PHASE_4_BROWSER_WORKSPACE_ENGINEERING_REPORT.md` for measured browser verification.
