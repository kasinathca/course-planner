"""Validate a private registration reference without printing identifying row data."""

from __future__ import annotations

import argparse
import json
import tempfile
from importlib import resources
from pathlib import Path
from typing import Any

from ffcs_studio.persistence.calendar_repository import CalendarRepository
from ffcs_studio.persistence.database import Database
from ffcs_studio.services.calendar_service import CalendarService
from ffcs_studio.services.timetable_validation import validate_registered_timetable


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--calendar", type=Path, required=True)
    parser.add_argument("--registrations", type=Path, required=True)
    args = parser.parse_args()
    calendar_payload = _object(args.calendar)
    registration_payload = _object(args.registrations)

    temporary_root = Path.cwd() / ".tmp"
    temporary_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="ffcs-calendar-check-", dir=temporary_root
    ) as temporary:
        database = Database(Path(temporary) / "check.sqlite3")
        database.initialize()
        repository = CalendarRepository(database)
        schema = json.loads(
            resources.files("ffcs_studio.resources.schemas")
            .joinpath("slot-calendar.schema.json")
            .read_text(encoding="utf-8")
        )
        service = CalendarService(repository, schema)
        validated = service.validate(calendar_payload)
        previewed = service.preview(str(validated["validation_id"]))
        committed = service.commit(str(previewed["preview_id"]), make_active=True)
        calendar = repository.get(str(committed["calendar_id"]))
        if calendar is None:
            raise RuntimeError("committed calendar could not be reloaded")
        if registration_payload.get("semester_label") != calendar.semester_label:
            raise ValueError("registration and calendar semesters do not match")
        if registration_payload.get("campus") != calendar.campus:
            raise ValueError("registration and calendar campuses do not match")
        components = registration_payload.get("components")
        if not isinstance(components, list) or not all(
            isinstance(component, dict) for component in components
        ):
            raise ValueError("registrations must contain a components array")
        result = validate_registered_timetable(components, calendar)

    print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    return 0 if result.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
