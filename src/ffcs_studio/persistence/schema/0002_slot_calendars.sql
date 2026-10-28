CREATE TABLE calendar_profiles (
    profile_id TEXT PRIMARY KEY,
    campus TEXT NOT NULL,
    semester_label TEXT NOT NULL,
    profile_name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(campus, semester_label, profile_name)
);

CREATE TABLE calendar_versions (
    calendar_id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL REFERENCES calendar_profiles(profile_id) ON DELETE RESTRICT,
    version INTEGER NOT NULL CHECK (version >= 1),
    schema_version TEXT NOT NULL,
    timezone TEXT NOT NULL CHECK (timezone = 'Asia/Kolkata'),
    verification_status TEXT NOT NULL CHECK (verification_status IN (
        'official_verified', 'evidence_supported', 'draft_unverified', 'user_supplied'
    )),
    evidence_kind TEXT NOT NULL,
    evidence_reference TEXT NOT NULL,
    reviewed_by TEXT,
    reviewed_at TEXT,
    evidence_notes TEXT,
    semantic_sha256 TEXT NOT NULL UNIQUE,
    canonical_json TEXT NOT NULL,
    committed_at TEXT NOT NULL,
    UNIQUE(profile_id, version),
    CHECK (
        verification_status != 'official_verified' OR
        (evidence_kind = 'official_document' AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)
    )
);

CREATE INDEX idx_calendar_versions_profile ON calendar_versions(profile_id, version DESC);

CREATE TABLE calendar_atomic_slots (
    atomic_slot_id INTEGER PRIMARY KEY,
    calendar_id TEXT NOT NULL REFERENCES calendar_versions(calendar_id) ON DELETE RESTRICT,
    slot_code TEXT NOT NULL,
    slot_ordinal INTEGER NOT NULL CHECK (slot_ordinal >= 1),
    UNIQUE(calendar_id, slot_code),
    UNIQUE(calendar_id, slot_ordinal)
);

CREATE TABLE calendar_intervals (
    interval_id INTEGER PRIMARY KEY,
    atomic_slot_id INTEGER NOT NULL REFERENCES calendar_atomic_slots(atomic_slot_id) ON DELETE RESTRICT,
    interval_ordinal INTEGER NOT NULL CHECK (interval_ordinal >= 1),
    weekday INTEGER NOT NULL CHECK (weekday BETWEEN 0 AND 6),
    start_minute INTEGER NOT NULL CHECK (start_minute BETWEEN 0 AND 1439),
    end_minute INTEGER NOT NULL CHECK (end_minute BETWEEN 1 AND 1440),
    meeting_kind TEXT NOT NULL CHECK (meeting_kind IN (
        'theory', 'lab', 'tutorial', 'project', 'soft_skills', 'other'
    )),
    session_id TEXT,
    CHECK (start_minute < end_minute),
    UNIQUE(atomic_slot_id, interval_ordinal)
);

CREATE TABLE active_calendars (
    campus TEXT NOT NULL,
    semester_label TEXT NOT NULL,
    calendar_id TEXT NOT NULL REFERENCES calendar_versions(calendar_id) ON DELETE RESTRICT,
    selected_at TEXT NOT NULL,
    PRIMARY KEY(campus, semester_label)
);

CREATE TABLE calendar_audit_events (
    event_id INTEGER PRIMARY KEY,
    calendar_id TEXT NOT NULL REFERENCES calendar_versions(calendar_id) ON DELETE RESTRICT,
    event_type TEXT NOT NULL,
    details_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE component_pairing_rules (
    pairing_rule_id INTEGER PRIMARY KEY,
    offering_revision_id INTEGER NOT NULL REFERENCES offering_revisions(revision_id) ON DELETE RESTRICT,
    left_allocation_id INTEGER NOT NULL REFERENCES allocation_rows(allocation_id) ON DELETE RESTRICT,
    right_allocation_id INTEGER NOT NULL REFERENCES allocation_rows(allocation_id) ON DELETE RESTRICT,
    pairing_state TEXT NOT NULL CHECK (pairing_state IN (
        'verified_allowed', 'verified_forbidden', 'provisional', 'inferred', 'unknown',
        'not_applicable'
    )),
    source_reference TEXT NOT NULL,
    created_at TEXT NOT NULL,
    invalidated_at TEXT,
    CHECK (left_allocation_id < right_allocation_id),
    UNIQUE(offering_revision_id, left_allocation_id, right_allocation_id)
);

CREATE INDEX idx_pairing_rules_revision
ON component_pairing_rules(offering_revision_id, invalidated_at);

CREATE TRIGGER component_pairing_rules_revision_insert
BEFORE INSERT ON component_pairing_rules
BEGIN
    SELECT CASE WHEN
        (SELECT revision_id FROM allocation_rows WHERE allocation_id = NEW.left_allocation_id)
            != NEW.offering_revision_id
        OR
        (SELECT revision_id FROM allocation_rows WHERE allocation_id = NEW.right_allocation_id)
            != NEW.offering_revision_id
    THEN RAISE(ABORT, 'pairing allocations must belong to the offering revision') END;
END;

CREATE TRIGGER component_pairing_rules_revision_update
BEFORE UPDATE OF offering_revision_id, left_allocation_id, right_allocation_id
ON component_pairing_rules
BEGIN
    SELECT CASE WHEN
        (SELECT revision_id FROM allocation_rows WHERE allocation_id = NEW.left_allocation_id)
            != NEW.offering_revision_id
        OR
        (SELECT revision_id FROM allocation_rows WHERE allocation_id = NEW.right_allocation_id)
            != NEW.offering_revision_id
    THEN RAISE(ABORT, 'pairing allocations must belong to the offering revision') END;
END;
