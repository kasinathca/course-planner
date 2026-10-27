from __future__ import annotations

import json
from pathlib import Path

from ffcs_studio.cli import main
from ffcs_studio.validation import load_validated_snapshot, validate_json_file

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas" / "vtop-export.schema.json"


def test_sanitized_fixtures_validate() -> None:
    for name in ("vtop_selected_theory_only.json", "vtop_selected_eth_ela.json"):
        report = validate_json_file(ROOT / "examples" / name, schema_path=SCHEMA)
        assert report.valid, report.issues
        assert load_validated_snapshot(report).allocation_count > 0


def test_malformed_record_reports_precise_json_pointer(tmp_path: Path, capsys) -> None:
    document = json.loads(
        (ROOT / "examples" / "vtop_selected_theory_only.json").read_text(encoding="utf-8")
    )
    del document["courses"][0]["allocations"][2]["faculty"]
    malformed = tmp_path / "malformed.json"
    malformed.write_text(json.dumps(document), encoding="utf-8")

    report = validate_json_file(malformed, schema_path=SCHEMA)

    assert not report.valid
    assert any(issue.path == "/courses/0/allocations/2" for issue in report.errors)
    assert any("faculty" in issue.message for issue in report.errors)
    assert main(["validate", str(malformed), "--schema", str(SCHEMA)]) == 1
    assert "INVALID" in capsys.readouterr().out


def test_unexpected_sensitive_field_is_rejected(tmp_path: Path) -> None:
    document = json.loads(
        (ROOT / "examples" / "vtop_selected_theory_only.json").read_text(encoding="utf-8")
    )
    document["auth_token"] = "must-not-be-accepted"
    path = tmp_path / "unsafe.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    report = validate_json_file(path, schema_path=SCHEMA)

    assert not report.valid
    assert any(issue.code == "schema_additionalProperties" for issue in report.errors)


def test_unknown_component_type_is_valid_but_warned_and_preserved(tmp_path: Path) -> None:
    document = json.loads(
        (ROOT / "examples" / "vtop_selected_theory_only.json").read_text(encoding="utf-8")
    )
    document["courses"][0]["allocations"][0]["course_type"] = "FUTURE_COMPONENT"
    path = tmp_path / "unknown.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    report = validate_json_file(path, schema_path=SCHEMA)

    assert report.valid
    assert report.warnings[0].code == "unknown_component_type"
    first_review = load_validated_snapshot(report).review_components[0]
    assert first_review.raw_row.course_type == "FUTURE_COMPONENT"


def test_invalid_json_includes_line_and_column(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text('{"schema_version":', encoding="utf-8")
    report = validate_json_file(path, schema_path=SCHEMA)
    assert not report.valid
    assert "line 1, column" in report.errors[0].message


def test_cli_exit_codes_and_output(capsys) -> None:
    valid = ROOT / "examples" / "vtop_selected_theory_only.json"
    assert main(["validate", str(valid), "--schema", str(SCHEMA)]) == 0
    assert "OK" in capsys.readouterr().out
