#!/usr/bin/env python3
"""Zero-dependency basic sanitizer/shape inspector for exported VTOP JSON."""

import json
import sys
from pathlib import Path
from typing import Any


def inspect(path: str) -> None:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    forbidden = {
        "_csrf",
        "csrf",
        "cookie",
        "password",
        "authorizedid",
        "registration_no",
        "student_id",
        "auth_token",
        "html",
    }
    if not isinstance(doc, dict) or doc.get("schema_version") != "1.0.0":
        raise ValueError("Missing/unsupported schema_version")
    if doc.get("source") != "vtop-tampermonkey":
        raise ValueError("Wrong source")
    metadata = ("campus", "semester_label", "captured_at")
    if any(not isinstance(doc.get(key), str) or not doc[key].strip() for key in metadata):
        raise ValueError("Missing capture metadata")
    if not isinstance(doc.get("courses"), list):
        raise ValueError("courses must be array")

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            if forbidden.intersection({key.lower() for key in obj}):
                raise ValueError("Unsafe field present")
            for value in obj.values():
                walk(value)
        elif isinstance(obj, list):
            for value in obj:
                walk(value)

    walk(doc)
    count = 0
    for course in doc["courses"]:
        for key in ("category", "course_code", "course_title"):
            if not isinstance(course.get(key), str) or not course[key].strip():
                raise ValueError("Bad course " + key)
        if not isinstance(course.get("allocations"), list):
            raise ValueError("Missing allocations")
        for number, row in enumerate(course["allocations"], 1):
            if not isinstance(row, dict) or row.get("source_row") != number:
                raise ValueError("Invalid source_row")
            for key in ("slot", "venue", "faculty", "course_type"):
                if not isinstance(row.get(key), str) or not row[key].strip():
                    raise ValueError("Missing " + key)
            count += 1
    print(
        f"OK: {len(doc['courses'])} course(s), {count} allocation row(s), {doc['semester_label']}"
    )


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python tools/inspect_capture.py examples/file.json ...")
    for source_path in sys.argv[1:]:
        inspect(source_path)
