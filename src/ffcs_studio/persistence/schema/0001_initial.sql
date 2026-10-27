CREATE TABLE IF NOT EXISTS app_state (
    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
    data_revision INTEGER NOT NULL DEFAULT 0 CHECK (data_revision >= 0),
    updated_at TEXT NOT NULL
);

INSERT OR IGNORE INTO app_state(singleton_id, data_revision, updated_at)
VALUES (1, 0, '1970-01-01T00:00:00+00:00');

CREATE TABLE import_snapshots (
    import_id TEXT PRIMARY KEY,
    source_format TEXT NOT NULL CHECK (source_format IN ('json', 'csv')),
    source_kind TEXT NOT NULL,
    metadata_origin TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    raw_sha256 TEXT NOT NULL,
    semantic_sha256 TEXT NOT NULL UNIQUE,
    campus TEXT NOT NULL,
    semester_label TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    course_count INTEGER NOT NULL CHECK (course_count >= 0),
    allocation_count INTEGER NOT NULL CHECK (allocation_count >= 0),
    canonical_json TEXT NOT NULL,
    committed_at TEXT NOT NULL
);

CREATE INDEX idx_import_snapshots_semester
ON import_snapshots(campus, semester_label, committed_at DESC);

CREATE TABLE courses (
    course_id INTEGER PRIMARY KEY,
    course_code TEXT NOT NULL,
    course_title TEXT NOT NULL,
    code_search TEXT NOT NULL,
    title_search TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(course_code, course_title)
);

CREATE INDEX idx_courses_search ON courses(code_search, title_search);

CREATE TABLE offerings (
    offering_id INTEGER PRIMARY KEY,
    campus TEXT NOT NULL,
    semester_label TEXT NOT NULL,
    category TEXT NOT NULL,
    course_code TEXT NOT NULL,
    active_course_id INTEGER REFERENCES courses(course_id),
    active_revision_id INTEGER REFERENCES offering_revisions(revision_id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(campus, semester_label, category, course_code)
);

CREATE INDEX idx_offerings_semester
ON offerings(campus, semester_label, category, course_code);

CREATE TABLE offering_revisions (
    revision_id INTEGER PRIMARY KEY,
    offering_id INTEGER NOT NULL REFERENCES offerings(offering_id) ON DELETE RESTRICT,
    import_id TEXT NOT NULL REFERENCES import_snapshots(import_id) ON DELETE RESTRICT,
    course_id INTEGER NOT NULL REFERENCES courses(course_id) ON DELETE RESTRICT,
    course_ordinal INTEGER NOT NULL CHECK (course_ordinal >= 1),
    raw_category TEXT NOT NULL,
    raw_course_code TEXT NOT NULL,
    raw_course_title TEXT NOT NULL,
    revision_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(import_id, course_ordinal)
);

CREATE INDEX idx_offering_revisions_offering
ON offering_revisions(offering_id, revision_id DESC);

CREATE TABLE allocation_rows (
    allocation_id INTEGER PRIMARY KEY,
    revision_id INTEGER NOT NULL REFERENCES offering_revisions(revision_id) ON DELETE RESTRICT,
    allocation_ordinal INTEGER NOT NULL CHECK (allocation_ordinal >= 1),
    source_row INTEGER NOT NULL CHECK (source_row >= 1),
    raw_slot TEXT NOT NULL,
    raw_venue TEXT NOT NULL,
    raw_faculty TEXT NOT NULL,
    raw_course_type TEXT NOT NULL,
    slot_search TEXT NOT NULL,
    venue_search TEXT NOT NULL,
    faculty_search TEXT NOT NULL,
    component_search TEXT NOT NULL,
    row_sha256 TEXT NOT NULL,
    UNIQUE(revision_id, allocation_ordinal)
);

CREATE INDEX idx_allocation_rows_revision
ON allocation_rows(revision_id, allocation_ordinal);
CREATE INDEX idx_allocation_rows_component
ON allocation_rows(component_search, revision_id);

CREATE TABLE import_warnings (
    warning_id INTEGER PRIMARY KEY,
    import_id TEXT NOT NULL REFERENCES import_snapshots(import_id) ON DELETE CASCADE,
    course_ordinal INTEGER,
    allocation_ordinal INTEGER,
    warning_code TEXT NOT NULL,
    json_path TEXT NOT NULL,
    message TEXT NOT NULL
);

CREATE INDEX idx_import_warnings_import ON import_warnings(import_id, warning_id);

CREATE TABLE reconciliation_events (
    event_id INTEGER PRIMARY KEY,
    import_id TEXT NOT NULL REFERENCES import_snapshots(import_id) ON DELETE CASCADE,
    offering_id INTEGER REFERENCES offerings(offering_id) ON DELETE RESTRICT,
    course_ordinal INTEGER NOT NULL CHECK (course_ordinal >= 1),
    event_type TEXT NOT NULL,
    detail_json TEXT NOT NULL,
    event_ordinal INTEGER NOT NULL CHECK (event_ordinal >= 1),
    UNIQUE(import_id, event_ordinal)
);

CREATE INDEX idx_reconciliation_events_import
ON reconciliation_events(import_id, event_ordinal);
