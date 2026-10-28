"""Evidence-aware prerequisite evaluation."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from ffcs_studio.degree.models import PrerequisiteRule


def evaluate_prerequisite(
    course_id: str,
    completed: set[str],
    semester: int,
    rules: tuple[PrerequisiteRule, ...],
    *,
    waivers: set[str] | None = None,
    equivalent_completed: set[str] | None = None,
) -> dict[str, Any]:
    if course_id in (waivers or set()):
        return {"status": "waived", "rule": None, "missing": []}
    rule = next((item for item in rules if item.course_id == course_id), None)
    if rule is None or not rule.verified:
        return {"status": "not_verified", "rule": asdict(rule) if rule else None, "missing": []}
    satisfied = completed | (equivalent_completed or set())
    missing = [item for item in rule.all_of if item not in satisfied]
    for group in rule.any_of:
        if not any(item in satisfied for item in group):
            missing.append(" OR ".join(group))
    if rule.minimum_semester is not None and semester < rule.minimum_semester:
        missing.append(f"minimum semester {rule.minimum_semester}")
    return {
        "status": "blocked" if missing else "satisfied",
        "rule": asdict(rule),
        "missing": missing,
    }
