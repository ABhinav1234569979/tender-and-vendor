CREATE TABLE IF NOT EXISTS parsed_documents (
    doc_id TEXT PRIMARY KEY,
    file_name TEXT NOT NULL,
    page INTEGER NOT NULL,
    bbox TEXT NOT NULL,
    text TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS master_specs (
    spec_row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_file TEXT NOT NULL,
    sheet_name TEXT NOT NULL DEFAULT '',
    spec_id TEXT NOT NULL,
    parameter_name TEXT NOT NULL,
    company_requirement TEXT NOT NULL,
    row_index INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_file, spec_id)
);

CREATE TABLE IF NOT EXISTS compliance_matrix (
    spec_id TEXT NOT NULL,
    vendor_id TEXT NOT NULL,
    status TEXT NOT NULL,
    citation TEXT NOT NULL,
    citation_doc_id TEXT,
    citation_excerpt TEXT,
    citation_page INTEGER,
    citation_bbox TEXT,
    reasoning TEXT NOT NULL,
    confidence REAL NOT NULL,
    PRIMARY KEY (spec_id, vendor_id)
);

CREATE TABLE IF NOT EXISTS autonomous_feedback_loop (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    spec_id TEXT NOT NULL,
    vendor_id TEXT NOT NULL,
    original_status TEXT NOT NULL,
    corrected_status TEXT NOT NULL,
    justification TEXT NOT NULL,
    context TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS training_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    spec_id TEXT NOT NULL,
    vendor_id TEXT NOT NULL,
    doc_id TEXT,
    page INTEGER,
    bbox TEXT,
    excerpt TEXT,
    label TEXT,
    processed INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    details TEXT NOT NULL DEFAULT '',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    progress REAL NOT NULL DEFAULT 0,
    message TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS application_users (
    username TEXT PRIMARY KEY,
    full_name TEXT NOT NULL DEFAULT '',
    hashed_password TEXT NOT NULL,
    disabled INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS format_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_name TEXT NOT NULL,
    sheet_name TEXT NOT NULL,
    profile_json TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(file_name, sheet_name)
);

CREATE TABLE IF NOT EXISTS heuristic_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_type TEXT NOT NULL,
    pattern TEXT NOT NULL,
    verdict TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 1.0,
    hit_count INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'system',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_format_profiles_file ON format_profiles(file_name);
CREATE INDEX IF NOT EXISTS idx_heuristic_rules_type ON heuristic_rules(rule_type);

