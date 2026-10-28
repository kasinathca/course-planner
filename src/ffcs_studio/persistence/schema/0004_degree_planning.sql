CREATE TABLE programmes (
    programme_id TEXT PRIMARY KEY,
    programme_code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    admission_batch TEXT NOT NULL,
    provenance TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE curriculum_revisions (
    curriculum_id TEXT PRIMARY KEY,
    programme_id TEXT NOT NULL REFERENCES programmes(programme_id) ON DELETE RESTRICT,
    revision_code TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('draft', 'reviewed', 'active', 'archived')),
    displayed_total_milli INTEGER NOT NULL CHECK (displayed_total_milli >= 0),
    nc_accounting_status TEXT NOT NULL,
    source_digest TEXT NOT NULL,
    source_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(programme_id, revision_code, source_digest)
);

CREATE TABLE programme_category_requirements (
    curriculum_id TEXT NOT NULL REFERENCES curriculum_revisions(curriculum_id) ON DELETE CASCADE,
    category_code TEXT NOT NULL,
    category_name TEXT NOT NULL,
    recorded_target_milli INTEGER NOT NULL CHECK (recorded_target_milli >= 0),
    confirmed_credit_target_milli INTEGER CHECK (confirmed_credit_target_milli >= 0),
    non_credit_target_units INTEGER NOT NULL DEFAULT 0 CHECK (non_credit_target_units >= 0),
    counted_in_graduation INTEGER CHECK (counted_in_graduation IN (0, 1)),
    surplus_allowed INTEGER NOT NULL CHECK (surplus_allowed IN (0, 1)),
    notes TEXT NOT NULL,
    PRIMARY KEY (curriculum_id, category_code)
);

CREATE TABLE curriculum_import_snapshots (
    curriculum_import_id TEXT PRIMARY KEY,
    curriculum_id TEXT REFERENCES curriculum_revisions(curriculum_id) ON DELETE RESTRICT,
    import_kind TEXT NOT NULL CHECK (import_kind IN ('canonical', 'legacy_v6')),
    original_filename TEXT NOT NULL,
    source_sequence INTEGER,
    source_digest TEXT NOT NULL UNIQUE,
    source_updated_at TEXT,
    raw_json TEXT NOT NULL,
    preview_json TEXT NOT NULL,
    committed_at TEXT NOT NULL
);

CREATE TABLE catalogue_courses (
    catalogue_course_id TEXT PRIMARY KEY,
    curriculum_id TEXT NOT NULL REFERENCES curriculum_revisions(curriculum_id) ON DELETE RESTRICT,
    canonical_identity TEXT NOT NULL,
    source_identity TEXT NOT NULL,
    source_order INTEGER NOT NULL CHECK (source_order >= 0),
    course_code TEXT NOT NULL,
    course_title TEXT NOT NULL,
    category_code TEXT NOT NULL,
    curriculum_type TEXT NOT NULL,
    lecture INTEGER CHECK (lecture >= 0),
    tutorial INTEGER CHECK (tutorial >= 0),
    practical INTEGER CHECK (practical >= 0),
    project INTEGER CHECK (project >= 0),
    total_credits_milli INTEGER CHECK (total_credits_milli >= 0),
    provenance TEXT NOT NULL,
    alternative_group TEXT,
    notes TEXT NOT NULL,
    unresolved_json TEXT NOT NULL,
    reviewed_revision INTEGER NOT NULL DEFAULT 1 CHECK (reviewed_revision >= 1),
    UNIQUE(curriculum_id, canonical_identity),
    UNIQUE(curriculum_id, source_identity)
);

CREATE INDEX idx_catalogue_course_search
ON catalogue_courses(curriculum_id, course_code, category_code, total_credits_milli);

CREATE TABLE course_relationships (
    relationship_id TEXT PRIMARY KEY,
    curriculum_id TEXT NOT NULL REFERENCES curriculum_revisions(curriculum_id) ON DELETE CASCADE,
    source_identity TEXT NOT NULL,
    relationship_type TEXT NOT NULL,
    requirement_key TEXT,
    verified INTEGER NOT NULL CHECK (verified IN (0, 1)),
    provenance TEXT NOT NULL,
    notes TEXT NOT NULL,
    course_ids_json TEXT NOT NULL,
    UNIQUE(curriculum_id, source_identity)
);

CREATE TABLE prerequisite_rules (
    prerequisite_rule_id TEXT PRIMARY KEY,
    curriculum_id TEXT NOT NULL REFERENCES curriculum_revisions(curriculum_id) ON DELETE CASCADE,
    source_identity TEXT NOT NULL,
    catalogue_course_id TEXT NOT NULL REFERENCES catalogue_courses(catalogue_course_id) ON DELETE CASCADE,
    all_of_json TEXT NOT NULL,
    any_of_json TEXT NOT NULL,
    minimum_semester INTEGER CHECK (minimum_semester BETWEEN 1 AND 10),
    verified INTEGER NOT NULL CHECK (verified IN (0, 1)),
    provenance TEXT NOT NULL,
    UNIQUE(curriculum_id, source_identity)
);

CREATE TABLE degree_plans (
    degree_plan_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    programme_id TEXT NOT NULL REFERENCES programmes(programme_id) ON DELETE RESTRICT,
    curriculum_id TEXT NOT NULL REFERENCES curriculum_revisions(curriculum_id) ON DELETE RESTRICT,
    current_revision INTEGER NOT NULL CHECK (current_revision >= 1),
    status TEXT NOT NULL CHECK (status IN ('active', 'draft', 'archived')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    archived_at TEXT
);

CREATE TABLE degree_plan_revisions (
    degree_plan_id TEXT NOT NULL REFERENCES degree_plans(degree_plan_id) ON DELETE CASCADE,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    document_json TEXT NOT NULL,
    change_summary TEXT NOT NULL,
    source_snapshot_id TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (degree_plan_id, revision)
);

CREATE TABLE degree_plan_entries (
    degree_plan_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    record_id TEXT NOT NULL,
    catalogue_course_id TEXT NOT NULL REFERENCES catalogue_courses(catalogue_course_id) ON DELETE RESTRICT,
    semester_number INTEGER NOT NULL CHECK (semester_number BETWEEN 0 AND 10),
    status TEXT NOT NULL CHECK (status IN ('planned', 'tentative', 'enrolled', 'completed', 'withdrawn', 'failed')),
    intended_category TEXT,
    attempt INTEGER NOT NULL DEFAULT 1 CHECK (attempt >= 1),
    offering_id INTEGER REFERENCES offerings(offering_id) ON DELETE RESTRICT,
    notes TEXT NOT NULL,
    provenance TEXT NOT NULL,
    PRIMARY KEY (degree_plan_id, revision, record_id),
    FOREIGN KEY (degree_plan_id, revision) REFERENCES degree_plan_revisions(degree_plan_id, revision) ON DELETE CASCADE
);

CREATE INDEX idx_degree_entries_semester
ON degree_plan_entries(degree_plan_id, revision, semester_number, status);

CREATE TABLE degree_scenario_links (
    link_id TEXT PRIMARY KEY,
    degree_plan_id TEXT NOT NULL,
    degree_plan_revision INTEGER NOT NULL,
    semester_number INTEGER NOT NULL CHECK (semester_number BETWEEN 1 AND 10),
    scenario_id TEXT NOT NULL REFERENCES saved_scenarios(scenario_id) ON DELETE RESTRICT,
    scenario_revision INTEGER NOT NULL CHECK (scenario_revision >= 1),
    mapping_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (degree_plan_id, degree_plan_revision) REFERENCES degree_plan_revisions(degree_plan_id, revision) ON DELETE RESTRICT
);

CREATE TABLE registration_availability_history (
    availability_id TEXT PRIMARY KEY,
    campus TEXT NOT NULL,
    semester_label TEXT NOT NULL,
    offering_revision_id INTEGER NOT NULL REFERENCES offering_revisions(revision_id) ON DELETE RESTRICT,
    allocation_id INTEGER NOT NULL REFERENCES allocation_rows(allocation_id) ON DELETE RESTRICT,
    state TEXT NOT NULL CHECK (state IN ('available', 'full', 'unavailable', 'registered', 'registration_failed', 'waitlisted', 'pending', 'unknown')),
    provenance TEXT NOT NULL,
    note TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    cleared_at TEXT
);

CREATE INDEX idx_availability_current
ON registration_availability_history(offering_revision_id, allocation_id, captured_at DESC);

CREATE TABLE recovery_runs (
    recovery_run_id TEXT PRIMARY KEY,
    scenario_id TEXT REFERENCES saved_scenarios(scenario_id) ON DELETE RESTRICT,
    scenario_revision INTEGER,
    source_revision_fingerprint TEXT NOT NULL,
    request_json TEXT NOT NULL,
    result_json TEXT NOT NULL,
    status TEXT NOT NULL,
    proven_minimum INTEGER NOT NULL CHECK (proven_minimum IN (0, 1)),
    created_at TEXT NOT NULL
);

CREATE TABLE recovery_decisions (
    recovery_decision_id TEXT PRIMARY KEY,
    recovery_run_id TEXT NOT NULL REFERENCES recovery_runs(recovery_run_id) ON DELETE RESTRICT,
    selected_result_index INTEGER NOT NULL CHECK (selected_result_index >= 0),
    note TEXT NOT NULL,
    created_at TEXT NOT NULL
);
