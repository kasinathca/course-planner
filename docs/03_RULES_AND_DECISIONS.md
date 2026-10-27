# Course components, validity rules and decisions

## Vocabulary (never mix)

- **Curriculum type:** TH (theory-only), ETL (embedded theory + practical lab), ETP (embedded theory + project), LO (lab only), ELJ (embedded lab + project), PJ/project, SS, etc. Stored separately from per-VTOP-row `Course Type`.
- **VTOP allocation `Course Type`:** usually `TH`, `ETH`, `ELA`, `EPJ`, `SS` in captured pages. These are rows to classify/group, not complete courses by themselves.
- **Slot code:** `B1+TB1`, `L49+L50`, `L1+L2+L15+L16`, `A1+TA1+TAA1`, `TAA1`, etc. A `+` can join periods of **one** component. Source must preserve the original exact string.
- **Offering:** a specific semester's offered course. A course code/title existing in the degree catalog does not imply it is currently offered.
- **Section:** one registrable allocation/component with source faculty, slot and venue. **Candidate registration** is a complete selection of required components for a course.

## Default component requirements (configurable)

| Curriculum kind | Components normally required | Count actual campus time | Pairing |
| --- | --- | --- | --- |
| TH | `TH` or `ETH` if explicitly mapped for the course | yes | one theory section |
| ETL | theory `ETH` + practical `ELA` | both | theory & lab must respect the saved faculty pairing policy |
| ETP | theory `ETH` + `EPJ` record where present | theory slots only unless a verified scheduled project meeting exists | project row is not a lab. `NIL` is a venue, not a timeslot. |
| LO | lab `ELA` / configured lab type | lab time | all required periods in that section |
| ELJ | lab + project | lab time; any verified project meeting | project separate from lab |
| SS | `SS` | per calendar | configurable mandatory status |
| Other | from course template | unknown until mapped | manual review |

For **ETP**, do not count an `EPJ` row with the **same `A1+TA1`** as an extra class. It may represent assessment work rather than contact hours; never convert it to lab on the basis of a duplicated slot. Preserve the row for evidence and credits.

## Theory–lab shift preference

Typical Vellore convention: suffix `1` theory slots are in morning, suffix `2` in evening; labs `L1–L30` are morning and `L31–L60` later. User prefers morning theory + evening lab, **or the reverse**. Treat as `prefer_opposite_shifts`, not a hard rule, unless the actual VIT semester policy disallows same-shift combinations. Some sections may encode constraints that require more than a simple opposite shift test. Make this a versioned campus rule switch.

## Faculty pairing: correctness first

Source tables may not include a shared group/section ID. Candidate generation rules:

1. If official section/linked registration identifiers exist, use them.
2. If user configured same-faculty requirement and both components have the same **normalized faculty identity**, pair them provisionally.
3. If different faculty are explicitly allowed, use a ruleset enumerating valid pairs; do **not** generate every cross-product merely because names differ.
4. In ambiguous cases produce an unresolved link warning; allow planning as `hypothetical` only, clearly labeled, until verified.
5. Preserve duplicate faculty names at distinct slots/rooms as separate options. No accidental collapse.

No hard rule that one course's theory and lab are necessarily the same faculty, different faculty, or any pair can be assumed from generic FFCS descriptions alone.

## Other invariants

- A course has at most one registration candidate per semester plan unless university explicitly supports parallel repeat sections (normally not).
- Same faculty name does **not** mean same registrable section; preserve slot, room, component.
- Subject category is explicitly the course's **programme-category assignment**, not inferred from subject code prefix.
- `NIL` venue is valid; not to be interpreted as absent allocation.
- Credit caps and category requirements are data-driven; small overshoot may be allowed **with warning** for category satisfaction but semester maximum is a distinct hard rule when applicable.
- Completed alternative/equivalent subjects satisfy specific requirements only according to an explicit equivalent-group mapping, never naive string matching.
- `ENG1902` and `ENG1903` exclusion follows user's curriculum note; verify exact institutional rule and semantics before treating as an irreversible prohibition.
- `STS3022` repeated catalog entries represent documented alternatives; do not drop one as a duplicate.
- “Fewer labs” = fewer **required scheduled lab sessions** (and optionally fewer days/hours) not merely number of words `Lab` in course titles. `ETP` project work is reported separately.

## Hard-vs-soft precedence

Hard campus/regulatory rules > immutable user-selected must-takes and pinned registrations > semester credit limits > user soft preferences. If locked must-takes are jointly impossible, explain rather than silently remove one. Rankings should be lexicographic when priority groups differ, so low-priority preferences cannot crowd out a must-take or clearly more important course.
