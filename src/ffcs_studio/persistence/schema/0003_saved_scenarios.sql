CREATE TABLE saved_scenarios (
    scenario_id TEXT PRIMARY KEY,
    name TEXT NOT NULL CHECK (length(trim(name)) BETWEEN 1 AND 120),
    description TEXT NOT NULL DEFAULT '' CHECK (length(description) <= 2000),
    campus TEXT NOT NULL DEFAULT '' CHECK (length(campus) <= 100),
    semester_label TEXT NOT NULL DEFAULT '' CHECK (length(semester_label) <= 200),
    calendar_id TEXT REFERENCES calendar_versions(calendar_id) ON DELETE RESTRICT,
    document_schema_version TEXT NOT NULL,
    current_revision INTEGER NOT NULL CHECK (current_revision >= 1),
    status TEXT NOT NULL CHECK (status IN ('draft', 'ready', 'stale', 'archived')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    archived_at TEXT
);

CREATE INDEX idx_saved_scenarios_list
ON saved_scenarios(archived_at, updated_at DESC, scenario_id);

CREATE INDEX idx_saved_scenarios_semester
ON saved_scenarios(campus, semester_label, updated_at DESC);

CREATE TABLE scenario_revisions (
    scenario_id TEXT NOT NULL REFERENCES saved_scenarios(scenario_id) ON DELETE CASCADE,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    document_json TEXT NOT NULL,
    source_references_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('draft', 'ready', 'stale')),
    change_summary TEXT NOT NULL CHECK (length(change_summary) <= 500),
    created_at TEXT NOT NULL,
    PRIMARY KEY(scenario_id, revision)
);

CREATE INDEX idx_scenario_revisions_history
ON scenario_revisions(scenario_id, revision DESC);

CREATE TABLE saved_timetable_results (
    saved_result_id TEXT PRIMARY KEY,
    scenario_id TEXT NOT NULL,
    scenario_revision INTEGER NOT NULL,
    name TEXT NOT NULL CHECK (length(trim(name)) BETWEEN 1 AND 120),
    solver_result_id TEXT NOT NULL,
    solver_fingerprint TEXT NOT NULL,
    calendar_id TEXT NOT NULL REFERENCES calendar_versions(calendar_id) ON DELETE RESTRICT,
    snapshot_schema_version TEXT NOT NULL,
    result_json TEXT NOT NULL,
    source_references_json TEXT NOT NULL,
    verification_status TEXT NOT NULL CHECK (verification_status IN ('verified', 'exploratory')),
    is_preferred INTEGER NOT NULL DEFAULT 0 CHECK (is_preferred IN (0, 1)),
    created_at TEXT NOT NULL,
    FOREIGN KEY(scenario_id, scenario_revision)
        REFERENCES scenario_revisions(scenario_id, revision) ON DELETE CASCADE,
    UNIQUE(scenario_id, solver_fingerprint, solver_result_id, name)
);

CREATE INDEX idx_saved_results_scenario
ON saved_timetable_results(scenario_id, created_at DESC, saved_result_id);

CREATE UNIQUE INDEX idx_saved_results_one_preferred
ON saved_timetable_results(scenario_id) WHERE is_preferred = 1;

PRAGMA user_version = 3;
