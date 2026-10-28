from __future__ import annotations

import json
from importlib import resources
from pathlib import Path

import pytest

from ffcs_studio.persistence.calendar_repository import CalendarRepository
from ffcs_studio.persistence.database import Database
from ffcs_studio.services.calendar_service import CalendarService, InvalidCalendar


def schema() -> dict[str, object]:
    text = (
        resources.files("ffcs_studio.resources.schemas")
        .joinpath("slot-calendar.schema.json")
        .read_text(encoding="utf-8")
    )
    return json.loads(text)


def draft_payload() -> dict[str, object]:
    return {
        "schema_version": "2.0.0",
        "campus": "Vellore",
        "semester_label": "SYNTHETIC",
        "profile_name": "Test calendar",
        "timezone": "Asia/Kolkata",
        "verification_status": "draft_unverified",
        "evidence": {"kind": "synthetic_test", "reference": "unit test"},
        "slots": {
            "A1": [{"day": 0, "start_minute": 480, "end_minute": 530, "kind": "theory"}],
            "L1": [
                {
                    "day": 0,
                    "start_minute": 500,
                    "end_minute": 550,
                    "kind": "lab",
                    "session_id": "lab-1",
                }
            ],
        },
    }


def service(tmp_path: Path) -> tuple[CalendarService, CalendarRepository, Database]:
    database = Database(tmp_path / "ffcs.sqlite3")
    assert database.initialize() == 4
    repository = CalendarRepository(database)
    return CalendarService(repository, schema()), repository, database


def test_migration_0002_preserves_phase1_tables(tmp_path: Path) -> None:
    _, _, database = service(tmp_path)
    with database.connection() as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert "import_snapshots" in tables
    assert "calendar_versions" in tables
    assert "component_pairing_rules" in tables


def test_validate_preview_commit_and_reload(tmp_path: Path) -> None:
    calendar_service, repository, _ = service(tmp_path)
    validated = calendar_service.validate(draft_payload())
    preview = calendar_service.preview(validated["validation_id"])
    committed = calendar_service.commit(preview["preview_id"])
    stored = repository.get(committed["calendar_id"])
    assert stored is not None
    assert stored.verification_status.value == "draft_unverified"
    assert list(stored.slots) == ["A1", "L1"]
    assert repository.list()[0]["active"] == 1


def test_duplicate_commit_is_idempotent(tmp_path: Path) -> None:
    calendar_service, repository, _ = service(tmp_path)
    first_validation = calendar_service.validate(draft_payload())
    first_preview = calendar_service.preview(first_validation["validation_id"])
    first = calendar_service.commit(first_preview["preview_id"])
    second_validation = calendar_service.validate(draft_payload())
    second_preview = calendar_service.preview(second_validation["validation_id"])
    second = calendar_service.commit(second_preview["preview_id"])
    assert second["status"] == "already_committed"
    assert second["calendar_id"] == first["calendar_id"]
    assert len(repository.list()) == 1


def test_versions_preserve_previous_calendar(tmp_path: Path) -> None:
    calendar_service, repository, _ = service(tmp_path)
    first_validation = calendar_service.validate(draft_payload())
    first = calendar_service.commit(
        calendar_service.preview(first_validation["validation_id"])["preview_id"]
    )
    changed = draft_payload()
    changed["slots"]["A1"][0]["end_minute"] = 540  # type: ignore[index]
    second_validation = calendar_service.validate(changed)
    second = calendar_service.commit(
        calendar_service.preview(second_validation["validation_id"])["preview_id"]
    )
    assert first["calendar_id"] != second["calendar_id"]
    versions = repository.list()
    assert [item["version"] for item in versions] == [2, 1]
    assert sum(int(item["active"]) for item in versions) == 1


def test_v1_is_supported_but_official_claim_is_downgraded(tmp_path: Path) -> None:
    calendar_service, _, _ = service(tmp_path)
    payload = {
        "schema_version": "1.0.0",
        "campus": "Vellore",
        "semester_label": "Legacy",
        "timezone": "Asia/Kolkata",
        "verification_status": "official_verified",
        "source_reference": "user supplied text",
        "slots": {"A1": [{"day": 0, "start_minute": 480, "end_minute": 530, "kind": "theory"}]},
    }
    result = calendar_service.validate(payload)
    assert result["calendar"]["verification_status"] == "user_supplied"
    assert {issue["code"] for issue in result["issues"]} == {
        "legacy_v1_upgraded",
        "official_claim_not_verified",
    }


def test_v2_official_claim_without_review_is_downgraded(tmp_path: Path) -> None:
    calendar_service, _, _ = service(tmp_path)
    payload = draft_payload()
    payload["verification_status"] = "official_verified"
    result = calendar_service.validate(payload)
    assert result["calendar"]["verification_status"] == "user_supplied"


def test_invalid_review_timestamp_is_rejected(tmp_path: Path) -> None:
    calendar_service, _, _ = service(tmp_path)
    payload = draft_payload()
    payload["evidence"] = {
        "kind": "official_document",
        "reference": "review fixture",
        "reviewed_by": "Reviewer",
        "reviewed_at": "not-a-date",
    }
    with pytest.raises(InvalidCalendar):
        calendar_service.validate(payload)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.update(schema_version="9.0.0"),
        lambda payload: payload.update(timezone="UTC"),
        lambda payload: payload.update(slots={}),
        lambda payload: payload["slots"].update({"BAD+CODE": payload["slots"]["A1"]}),
    ],
)
def test_invalid_calendar_contracts_are_rejected(tmp_path: Path, mutation) -> None:
    calendar_service, _, _ = service(tmp_path)
    payload = draft_payload()
    mutation(payload)
    with pytest.raises(InvalidCalendar):
        calendar_service.validate(payload)
