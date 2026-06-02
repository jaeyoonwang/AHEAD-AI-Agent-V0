#!/usr/bin/env python3
"""
SQLite schema and helpers for the AHEAD AI agent.

Tables:
  contacts            — people in the DQ notification cascade
  org_unit_hierarchy  — pre-cached parent chain per facility (facility→woreda→zone→region)
  issues              — detected DQ issues and their resolution lifecycle
  conversations       — active SMS conversations keyed by phone number
  poll_state          — lastUpdated cursor for the DHIS2 change-detection poll
"""

import sqlite3, random, pathlib

DB_PATH  = pathlib.Path(__file__).parent / 'agent.db'
_CHARSET = '3456789ABCDEFGHJKMNPQRSTUVWXY'  # 29 chars; excludes 0/O/1/I/L/2/Z

_SCHEMA = """
CREATE TABLE IF NOT EXISTS contacts (
    id              INTEGER PRIMARY KEY,
    dhis2_username  TEXT UNIQUE,
    phone           TEXT,
    email           TEXT,
    covers_uid      TEXT,  -- UID of the org unit this contact is responsible for
    covers_name     TEXT,
    level           TEXT,  -- facility / woreda / zone / region / national
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS org_unit_hierarchy (
    facility_uid    TEXT PRIMARY KEY,
    facility_name   TEXT,
    woreda_uid      TEXT,
    woreda_name     TEXT,
    zone_uid        TEXT,
    zone_name       TEXT,
    region_uid      TEXT,
    region_name     TEXT,
    national_uid    TEXT
);

CREATE TABLE IF NOT EXISTS issues (
    id               INTEGER PRIMARY KEY,
    ref_id           TEXT UNIQUE NOT NULL,
    issue_type       TEXT NOT NULL,           -- outlier / dtp / missing
    facility_uid     TEXT NOT NULL,
    facility_name    TEXT NOT NULL,
    period           TEXT NOT NULL,           -- YYYYMM
    data_element     TEXT,                    -- BCG / Penta1 / Penta3 / MR1; NULL for missing reports
    flagged_value    REAL,
    expected_low     REAL,
    expected_high    REAL,
    status           TEXT DEFAULT 'open',     -- open / resolved / escalated / ignored
    cascade_level    TEXT DEFAULT 'facility', -- current notification level
    notified_at      DATETIME,
    last_retry_at    DATETIME,
    retry_count      INTEGER DEFAULT 0,
    resolved_at      DATETIME,
    resolution_notes TEXT,
    created_at       DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS conversations (
    id              INTEGER PRIMARY KEY,
    issue_ref_id    TEXT NOT NULL,
    phone           TEXT NOT NULL,
    state           TEXT DEFAULT 'awaiting_option', -- awaiting_option / awaiting_followup / closed
    selected_option INTEGER,
    followup_value  TEXT,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (issue_ref_id) REFERENCES issues(ref_id)
);

CREATE TABLE IF NOT EXISTS poll_state (
    key     TEXT PRIMARY KEY,
    value   TEXT
);

CREATE INDEX IF NOT EXISTS idx_conv_phone      ON conversations(phone, state);
CREATE INDEX IF NOT EXISTS idx_issues_status   ON issues(status, cascade_level);
CREATE INDEX IF NOT EXISTS idx_issues_facility ON issues(facility_uid, period);
"""


def get_conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA foreign_keys=ON')
    return conn


def init_db():
    """Create all tables. Safe to call on every startup (idempotent)."""
    with get_conn() as conn:
        conn.executescript(_SCHEMA)


def gen_ref_id(conn):
    """Generate a unique DQ-XXXX reference ID (29^4 ≈ 708K combinations)."""
    for _ in range(100):
        ref = 'DQ-' + ''.join(random.choices(_CHARSET, k=4))
        if not conn.execute('SELECT 1 FROM issues WHERE ref_id=?', (ref,)).fetchone():
            return ref
    raise RuntimeError('Could not generate unique ref_id after 100 attempts')


def get_active_conversation(conn, phone):
    """Return the most-recently-updated open conversation for a phone number, or None."""
    return conn.execute(
        "SELECT * FROM conversations WHERE phone=? AND state != 'closed'"
        " ORDER BY updated_at DESC LIMIT 1",
        (phone,)
    ).fetchone()


def get_contact_for_escalation(conn, facility_uid, level):
    """
    Return the contact responsible for a given issue at the requested cascade level.

    Looks up the cached hierarchy to find the woreda/zone/region UID that contains
    the facility, then returns the contact whose covers_uid matches.
    """
    if level == 'facility':
        covers_uid = facility_uid
    else:
        row = conn.execute(
            'SELECT * FROM org_unit_hierarchy WHERE facility_uid=?', (facility_uid,)
        ).fetchone()
        if not row:
            return None
        covers_uid = row[f'{level}_uid']
    return conn.execute(
        'SELECT * FROM contacts WHERE covers_uid=? AND level=?',
        (covers_uid, level)
    ).fetchone()


def seed_hierarchy(uid_map):
    """
    Populate org_unit_hierarchy from the UID map produced by dhis2/build_ethiopia.py.
    Called once during agent setup; idempotent (INSERT OR REPLACE).
    """
    woreda_by_uid = {v['uid']: v for v in uid_map.get('woredas', {}).values()}
    zone     = uid_map.get('north_gondar', {})
    region   = uid_map.get('amhara', {})
    national = uid_map.get('ethiopia', {})

    with get_conn() as conn:
        for fac in uid_map.get('facilities', {}).values():
            w_uid  = fac.get('woreda_uid', '')
            woreda = woreda_by_uid.get(w_uid, {})
            conn.execute("""
                INSERT OR REPLACE INTO org_unit_hierarchy
                  (facility_uid, facility_name,
                   woreda_uid,   woreda_name,
                   zone_uid,     zone_name,
                   region_uid,   region_name,
                   national_uid)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                fac['uid'],             fac['name'],
                w_uid,                  woreda.get('name', ''),
                zone.get('uid', ''),    zone.get('name', ''),
                region.get('uid', ''),  region.get('name', ''),
                national.get('uid', ''),
            ))
