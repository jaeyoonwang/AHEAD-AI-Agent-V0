#!/usr/bin/env python3
"""Generates AHEAD_AI_Tech_Architecture.docx — MVP implementation specification.
Run: pip install python-docx && python3 generate_tech_doc.py
"""
from docx import Document
from docx.shared import Pt, RGBColor, Inches, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

doc = Document()
section = doc.sections[0]
section.top_margin    = Cm(2.0)
section.bottom_margin = Cm(2.0)
section.left_margin   = Cm(2.5)
section.right_margin  = Cm(2.5)
doc.styles['Normal'].font.name = 'Calibri'
doc.styles['Normal'].font.size = Pt(10.5)

def h1(t):
    p = doc.add_heading(t, 1)
    p.runs[0].font.color.rgb = RGBColor(0x1F, 0x3A, 0x6E)
    p.runs[0].font.size = Pt(15)
def h2(t):
    p = doc.add_heading(t, 2)
    p.runs[0].font.color.rgb = RGBColor(0x2E, 0x6D, 0xA4)
    p.runs[0].font.size = Pt(12)
def body(t):
    p = doc.add_paragraph(t)
    if p.runs: p.runs[0].font.size = Pt(10.5)
def bullet(t, lv=0):
    p = doc.add_paragraph(t, style='List Bullet')
    p.paragraph_format.left_indent = Inches(0.25 * (lv + 1))
def mono(t):
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Inches(0.4)
    run = p.add_run(t)
    run.font.name = 'Courier New'
    run.font.size = Pt(8.5)
    run.font.color.rgb = RGBColor(0x33, 0x33, 0x33)
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear'); shd.set(qn('w:color'), 'auto'); shd.set(qn('w:fill'), 'F2F2F2')
    p._p.get_or_add_pPr().append(shd)
def tbl(headers, rows):
    t = doc.add_table(rows=1 + len(rows), cols=len(headers))
    t.style = 'Table Grid'; t.alignment = WD_TABLE_ALIGNMENT.LEFT
    hc = t.rows[0].cells
    for i, h in enumerate(headers):
        hc[i].text = h
        run = hc[i].paragraphs[0].runs[0]; run.bold = True; run.font.size = Pt(10)
        shd = OxmlElement('w:shd')
        shd.set(qn('w:val'), 'clear'); shd.set(qn('w:color'), 'auto'); shd.set(qn('w:fill'), 'D6E4F0')
        hc[i]._tc.get_or_add_tcPr().append(shd)
    for ri, row in enumerate(rows):
        cells = t.rows[ri + 1].cells
        for ci, val in enumerate(row):
            cells[ci].text = val
            if cells[ci].paragraphs[0].runs:
                cells[ci].paragraphs[0].runs[0].font.size = Pt(10)
def sp(): doc.add_paragraph('')


# ── Title ─────────────────────────────────────────────────────────────────────
title = doc.add_heading('AHEAD AI Agent — Technical Architecture', 0)
title.alignment = WD_ALIGN_PARAGRAPH.LEFT
title.runs[0].font.color.rgb = RGBColor(0x1F, 0x3A, 0x6E)
title.runs[0].font.size = Pt(18)
sub = doc.add_paragraph('MVP Implementation Specification  |  UNICEF AHEAD × Gates Foundation AI Fellows  |  June 2026')
sub.runs[0].font.size = Pt(9); sub.runs[0].font.color.rgb = RGBColor(0x88, 0x88, 0x88); sub.runs[0].italic = True
sp()

# ── 1. Overview ───────────────────────────────────────────────────────────────
h1('1. Overview')
body('This document specifies the technical implementation of the AHEAD AI agent MVP. The agent monitors immunization data quality across the Ethiopia org unit hierarchy by running three automated checks against the DHIS2 REST API after each data submission. When an issue is detected, it drives a structured SMS cascade — notifying the responsible person at the facility level first, retrying for 72 hours, then escalating upward through woreda, zone, region, and national — until the issue is resolved or dismissed. The agent runs as a standalone Python service alongside the existing DHIS2 Docker instance, requiring no changes to DHIS2 itself.')
sp()
body('This specification covers the DHIS2 service account, DQ engine checks (with exact API endpoints), SQLite database schema, cascade state machine, Claude API integration, Twilio SMS integration, Flask application endpoints, APScheduler jobs, Docker Compose deployment, and all environment variables.')
sp()

# ── 2. Architecture Diagram ───────────────────────────────────────────────────
h1('2. Architecture Diagram')
mono(
    '  Docker host\n'
    '  ┌─────────────────────────────────────────────────────────────────────┐\n'
    '  │                                                                     │\n'
    '  │  ┌──────────────┐    REST API     ┌───────────────────────────────┐ │\n'
    '  │  │  DHIS2 2.40  │◄───────────────│  AHEAD Agent (Python)         │ │\n'
    '  │  │  port 8080   │                │                               │ │\n'
    '  │  └──────────────┘                │  ┌─────────────┐              │ │\n'
    '  │                                  │  │  DQ Engine  │              │ │\n'
    '  │  ┌──────────────┐                │  │  3 checks   │              │ │\n'
    '  │  │  PostgreSQL  │  (DHIS2 only)  │  └──────┬──────┘              │ │\n'
    '  │  └──────────────┘                │         │ issues              │ │\n'
    '  │                                  │  ┌──────▼──────┐              │ │\n'
    '  │  ┌──────────────┐                │  │State Machine│              │ │\n'
    '  │  │  SQLite DB   │◄───────────────│  │  cascade    │              │ │\n'
    '  │  │  agent/db/   │                │  └─────────────┘              │ │\n'
    '  │  └──────────────┘                │                               │ │\n'
    '  │                                  │  ┌─────────────┐ ┌──────────┐ │ │\n'
    '  │                                  │  │    Flask    │ │APScheduler│ │ │\n'
    '  │                                  │  │  port 5001  │ │  jobs    │ │ │\n'
    '  │                                  │  └─────────────┘ └──────────┘ │ │\n'
    '  │                                  └───────────────────────────────┘ │\n'
    '  └─────────────────────────────────────────────────────────────────────┘\n'
    '\n'
    '  Inbound SMS  ──►  Twilio  ──►  POST /webhook/sms  ──►  state machine\n'
    '  Outbound SMS ◄──  Twilio  ◄──  agent sends via Twilio REST API\n'
    '  Claude API   ◄──► agent (parse replies, generate messages)\n'
    '  Supervisors  ──►  browser  ──►  GET /issues  (issue log page)'
)
sp()

# ── 3. DHIS2 Service Account ──────────────────────────────────────────────────
h1('3. DHIS2 Service Account')
body('The agent authenticates to DHIS2 as a dedicated service account (agent_service) with national-level scope. This is separate from all human role-based accounts. Human accounts enforce data-entry access control; the agent account exists solely to read all data for DQ checks and write confirmed corrections. It must never be used for manual data entry.')
sp()
tbl(
    ['Property', 'Value', 'Reason'],
    [
        ['Username', 'agent_service',
         'Identifiable in DHIS2 audit log; distinct from human accounts'],
        ['Data entry org unit', 'Ethiopia (national root)',
         'Must write corrections at any facility in the hierarchy'],
        ['Data view org unit', 'Ethiopia (national root)',
         'Must read data from any facility to run DQ checks'],
        ['User role authorities', 'F_DATAVALUE_ADD, F_DATAVALUE_DELETE',
         'Read + write dataValueSets only — no metadata, settings, or user management'],
        ['Created by', 'build_users.py (add agent block)',
         'Reproducible setup; credentials set via AGENT_USER / AGENT_PASS in .env'],
    ]
)
sp()
body('All DHIS2 API calls made by the agent use HTTP Basic Auth with these credentials, read from environment variables at startup. Credentials are never hardcoded.')
sp()

# ── 4. DQ Engine ──────────────────────────────────────────────────────────────
h1('4. DQ Engine: Three Checks')
body('The agent runs three checks against the DHIS2 REST API. Each is a single HTTP request. Results are consolidated, deduplicated against open issues in the database, and new issue records are created for any new violations. Checks run every 5 minutes (outlier, DTP consistency) and once daily (missing reports).')
sp()

h2('4.1  Outlier detection')
body('Uses the DHIS2 built-in outlier detection endpoint, which computes Z-scores for each data value against the same facility\'s historical baseline. The threshold defaults to 3.0 standard deviations and is configurable in config.py without a code change.')
mono(
    'GET /api/outlierDetection\n'
    '  ?ds=vI4ihClxSm4          # EPI - Routine vaccine delivery\n'
    '  &ou=RFhqluFmvRG          # Ethiopia root — scans all children\n'
    '  &startDate=2025-11-01\n'
    '  &endDate=2026-04-30\n'
    '  &algorithm=Z_SCORE\n'
    '  &threshold=3.0\n'
    '  &maxResults=100\n'
    '\n'
    'Response: list of {\n'
    '  dataElement, orgUnit, period, categoryOptionCombo,\n'
    '  value, mean, stdDev, zScore, followUp\n'
    '}'
)
sp()

h2('4.2  DTP1/DTP3 consistency')
body('Uses DHIS2\'s validation rule engine. The EPI Aggregate Metadata Package v1.1.0 ships with a built-in validation rule: Penta3 <= Penta1. The agent triggers a fresh validation run for the target period, then reads the results. Both steps are required in DHIS2 2.40 — results are not stored persistently until the run is explicitly triggered.')
mono(
    '# Step 1 — trigger validation run\n'
    'POST /api/validation\n'
    'Body: {\n'
    '  "organisationUnit": "RFhqluFmvRG",\n'
    '  "startPeriod": "202604",\n'
    '  "endPeriod":   "202604"\n'
    '}\n'
    '\n'
    '# Step 2 — read results\n'
    'GET /api/validationResults\n'
    '  ?ou=RFhqluFmvRG\n'
    '  &startPeriod=202604\n'
    '  &endPeriod=202604\n'
    '\n'
    'Response: list of {\n'
    '  validationRule {id, name},\n'
    '  orgUnit {id, name},\n'
    '  period,\n'
    '  leftsideValue,   # Penta3 value\n'
    '  rightsideValue   # Penta1 value\n'
    '}'
)
sp()

h2('4.3  Missing report detection')
body('Queries the complete dataset registration log to find which facilities submitted for the target period. Compares against the expected list (all level-5 org units assigned to the EPI dataset). Any facility present in expected but absent from registrations is flagged. Runs daily starting on day 5 of the following month.')
mono(
    'GET /api/completeDataSetRegistrations\n'
    '  ?dataSet=vI4ihClxSm4\n'
    '  &orgUnit=RFhqluFmvRG\n'
    '  &startPeriod=202604\n'
    '  &endPeriod=202604\n'
    '  &children=true\n'
    '\n'
    'Expected facilities: all org units at level 5 with dataset vI4ihClxSm4 assigned.\n'
    'Missing = expected_set - {r["organisationUnit"]["id"] for r in response}'
)
sp()

h2('4.4  Applying corrections')
body('When a facility worker confirms a corrected value via SMS, the agent writes it back to DHIS2 using the standard dataValueSets API — identical to any user submitting data — authenticated as agent_service. After writing, the agent re-runs all three checks for that facility-period to confirm the correction resolved the issue.')
mono(
    'POST /api/dataValueSets\n'
    'Body: {\n'
    '  "dataSet":    "vI4ihClxSm4",\n'
    '  "orgUnit":    "<facility UID>",\n'
    '  "period":     "202604",\n'
    '  "dataValues": [\n'
    '    {\n'
    '      "dataElement":        "<DE UID>",\n'
    '      "categoryOptionCombo": "<COC UID>",\n'
    '      "value":              "35"\n'
    '    }\n'
    '  ]\n'
    '}'
)
sp()

h2('4.5  Deduplication')
body('Before creating a new issue, the agent queries the database for any open issue with the same (org_unit_uid, period, check_type, data_element_uid). If one exists and is not yet resolved or dismissed, the detection is skipped silently. This prevents duplicate SMS notifications when the same violation appears on successive 5-minute poll cycles.')
sp()

# ── 5. Database Schema ────────────────────────────────────────────────────────
h1('5. Database Schema (SQLite → PostgreSQL in production)')
body('Three tables. All timestamps stored as ISO-8601 UTC strings. The schema is PostgreSQL-compatible — migration from SQLite requires only changing the connection string and TEXT PRIMARY KEY to SERIAL/UUID where appropriate.')
sp()

h2('issues')
mono(
    'CREATE TABLE issues (\n'
    '  id               TEXT PRIMARY KEY,      -- DQ-AX42\n'
    '  check_type       TEXT NOT NULL,         -- outlier | missing_report | dtp_inconsistency\n'
    '  org_unit_uid     TEXT NOT NULL,\n'
    '  facility_name    TEXT NOT NULL,\n'
    '  woreda_name      TEXT NOT NULL,\n'
    '  period           TEXT NOT NULL,         -- YYYYMM e.g. 202604\n'
    '  data_element_uid TEXT,                  -- NULL for missing_report\n'
    '  data_element_name TEXT,\n'
    '  coc_uid          TEXT,                  -- categoryOptionCombo UID\n'
    '  flagged_value    TEXT,                  -- NULL for missing_report\n'
    '  proposed_value   TEXT,                  -- current agent-proposed correction\n'
    '  resolved_value   TEXT,                  -- confirmed final value\n'
    '  status           TEXT NOT NULL DEFAULT \'notified\',\n'
    '                                          -- notified | awaiting_confirm\n'
    '                                          -- | resolved | dismissed | escalated\n'
    '  cascade_level    INTEGER NOT NULL DEFAULT 1,\n'
    '                                          -- 1=facility 2=woreda 3=zone\n'
    '                                          -- 4=region   5=national\n'
    '  retry_count      INTEGER NOT NULL DEFAULT 0,\n'
    '  opened_at        TEXT NOT NULL,\n'
    '  last_contact_at  TEXT,\n'
    '  resolved_at      TEXT\n'
    ');'
)
sp()

h2('conversations')
mono(
    'CREATE TABLE conversations (\n'
    '  id        INTEGER PRIMARY KEY AUTOINCREMENT,\n'
    '  issue_id  TEXT NOT NULL REFERENCES issues(id),\n'
    '  direction TEXT NOT NULL,    -- outbound | inbound\n'
    '  phone     TEXT NOT NULL,    -- E.164 format\n'
    '  body      TEXT NOT NULL,\n'
    '  sent_at   TEXT NOT NULL     -- ISO-8601 UTC\n'
    ');'
)
sp()

h2('contacts')
mono(
    'CREATE TABLE contacts (\n'
    '  org_unit_uid  TEXT    NOT NULL,\n'
    '  level         INTEGER NOT NULL,  -- 1=national 2=region 3=zone 4=woreda 5=facility\n'
    '  name          TEXT    NOT NULL,  -- person name\n'
    '  phone         TEXT    NOT NULL,  -- E.164 format\n'
    '  PRIMARY KEY (org_unit_uid, level)\n'
    ');\n'
    '\n'
    '-- Maintained manually by the AHEAD team. Not auto-populated from DHIS2 users.\n'
    '-- Seeded from a CSV for the prototype (one phone per org unit per level).'
)
sp()

# ── 6. Cascade State Machine ──────────────────────────────────────────────────
h1('6. Cascade State Machine')
mono(
    '                   Issue detected\n'
    '                        │\n'
    '                        ▼\n'
    '               ┌─────────────────┐\n'
    '               │    NOTIFIED     │  Initial SMS sent to facility\n'
    '               └────────┬────────┘\n'
    '                        │\n'
    '           ┌────────────┼──────────────────┐\n'
    '    Reply  │            │ No reply 24h      │ KEEP\n'
    '  (value)  │            │ (retry_count < 3) │\n'
    '           │            ▼                   ▼\n'
    '           │     retry SMS sent      ┌─────────────┐\n'
    '           │     retry_count++       │  DISMISSED  │\n'
    '           │            │            └─────────────┘\n'
    '           │    3 retries exhausted\n'
    '           │            │\n'
    '           │            ▼\n'
    '           │    ┌────────────────┐\n'
    '           │    │   ESCALATED    │  Summary sent to next level\n'
    '           │    │ cascade_level++│  (woreda → zone → region → national)\n'
    '           │    └────────────────┘\n'
    '           │\n'
    '           ▼\n'
    '   ┌────────────────────┐\n'
    '   │  AWAITING_CONFIRM  │  Agent proposes specific change\n'
    '   └──────┬─────────────┘\n'
    '          │\n'
    '    ┌─────┼────────────────────┐\n'
    '    YES   NO / different value  │\n'
    '    │     │                    │\n'
    '    ▼     ▼                    │\n'
    '┌──────┐  Re-send confirmation  │\n'
    '│RESOL-│  with updated value    │\n'
    '│ VED  │  (loop back up)        │\n'
    '└──────┘'
)
sp()
tbl(
    ['Status', 'Trigger', 'Agent action'],
    [
        ['notified',
         'Issue first detected by DQ engine',
         'Send initial SMS to facility contact; record last_contact_at'],
        ['notified → retry',
         'No inbound reply within 24h; retry_count < 3',
         'Re-send SMS with retry count label; increment retry_count'],
        ['notified → escalated',
         'retry_count reaches 3 (72h elapsed)',
         'Send summary SMS to next-level contact; increment cascade_level'],
        ['notified → awaiting_confirm',
         'Inbound SMS contains a numeric value',
         'Claude parses value; agent sends confirmation SMS with proposed change'],
        ['awaiting_confirm → resolved',
         'Inbound YES (or confirm)',
         'POST corrected value to DHIS2; set resolved_value, resolved_at; send closure SMS'],
        ['awaiting_confirm → dismissed',
         'Inbound KEEP',
         'Leave DHIS2 value unchanged; set status=dismissed; send acknowledgement SMS'],
        ['awaiting_confirm → awaiting_confirm',
         'Inbound NO or different number',
         'Update proposed_value; re-send confirmation SMS with new proposed change'],
    ]
)
sp()
h2('Escalation timing')
tbl(
    ['Level', 'Recipient', 'Trigger', 'SLA to next level'],
    [
        ['1 — Facility',  'Facility worker',         'Issue detected',                '72h (3 × 24h retries)'],
        ['2 — Woreda',    'Woreda HMIS officer',      '72h no facility resolution',    '1 week'],
        ['3 — Zone',      'Zone officer',             '1 week no woreda resolution',   '1 week'],
        ['4 — Region',    'Regional focal point',     '1 week no zone resolution',     'Until end of month'],
        ['5 — National',  'National TWG',             'End of month digest (all open issues)', 'N/A'],
    ]
)
sp()

# ── 7. Claude API Integration ─────────────────────────────────────────────────
h1('7. Claude API Integration')
body('Claude is used for two bounded tasks. Hallucination risk is low in both cases because neither is open-ended generation — the agent operates on a tightly scoped context (one issue, one numeric value).')
sp()
tbl(
    ['Task', 'Model', 'Input', 'Output', 'Max tokens'],
    [
        ['Parse inbound reply',
         'claude-haiku-4-5',
         'SMS body + issue context (facility, type, flagged value, proposed value)',
         'JSON: {"intent": "correct"|"keep"|"unknown", "value": <int>|null}',
         '50'],
        ['Generate outbound message',
         'claude-haiku-4-5',
         'Issue type + facility name + flagged value + proposed correction + message type',
         'SMS text under 160 characters',
         '120'],
    ]
)
sp()
body('Prompt caching (cache_control: ephemeral) is applied to the system prompt for each task, reducing cost and latency on rapid back-and-forth exchanges. The user turn (the specific SMS body or issue values) is never cached as it changes each call.')
sp()
mono(
    '# Parse reply — system prompt (cached)\n'
    '"You extract the intended corrected value from a facility health worker\'s SMS reply.\n'
    ' Facility: Limalimo HP. Issue DQ-AX42: BCG under-1 reported as 350. Agent proposed 35.\n'
    ' Respond with JSON only. No other text.\n'
    ' Schema: {"intent": "correct"|"keep"|"unknown", "value": <integer or null>}\n'
    ' intent=correct if the worker is giving a number. keep if they say KEEP or leave it.\n'
    ' unknown if the message is ambiguous."\n'
    '\n'
    '# User turn (not cached)\n'
    '"no wait, should be 53"\n'
    '\n'
    '# Expected response\n'
    '{"intent": "correct", "value": 53}'
)
sp()

# ── 8. SMS Integration ────────────────────────────────────────────────────────
h1('8. SMS Integration (Twilio)')
h2('Outbound')
body('Agent calls the Twilio Messages API directly via HTTPS. One SMS per issue event. Woreda-level and above notifications are batched summaries (one SMS per summary, not one per issue).')
mono(
    'POST https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Messages\n'
    '  From = TWILIO_FROM_NUMBER   (E.164 format, e.g. +12015551234)\n'
    '  To   = <recipient phone from contacts table>\n'
    '  Body = <message text>\n'
    '\n'
    '  On success: HTTP 201, sid returned and logged to conversations table\n'
    '  On failure: log error, retry once after 60s, then mark issue with send_error flag'
)
sp()

h2('Inbound (webhook routing)')
body('Twilio posts inbound SMS to POST /webhook/sms. The agent extracts the reference ID from the message body using a regex, looks up the corresponding open issue, and routes the body to the reply handler.')
mono(
    'POST /webhook/sms\n'
    '  Twilio params: From (sender phone), Body (SMS text), MessageSid\n'
    '\n'
    '  1. Extract ref ID:  re.search(r\'DQ-[A-Z0-9]{4}\', body.upper())\n'
    '  2. Query DB:        SELECT * FROM issues WHERE id=? AND status NOT IN (\'resolved\',\'dismissed\')\n'
    '  3. Not found:       reply "Ref ID not recognised. View issues at <url>"\n'
    '  4. Found:           pass to reply_handler(issue, sms_body)\n'
    '                         → Claude parse\n'
    '                         → state transition\n'
    '                         → Twilio response (TwiML or REST post-reply)\n'
    '  5. No ref ID at all: check if From number has exactly one open issue\n'
    '                         → if yes, route to that issue\n'
    '                         → if multiple, ask worker to include the ref ID'
)
sp()

h2('Reference ID format')
body('Format: DQ-XXXX (4-character suffix). Character set excludes visually ambiguous characters (0/O, 1/I/L, 2/Z). Remaining set: A B C D E F G H J K M N P Q R S T U V W X Y  +  3 4 5 6 7 8 9 = 29 characters. DQ-XXXX gives 29^4 = 707,281 unique IDs — sufficient for MVP. IDs are never reused; resolved issues keep their original ID for audit purposes.')
sp()

# ── 9. Flask Application ──────────────────────────────────────────────────────
h1('9. Flask Application')
body('A single Flask process on port 5001 handles the inbound SMS webhook and serves the issue log web page. Runs in the same Docker container as the scheduler and DQ engine.')
sp()
tbl(
    ['Endpoint', 'Method', 'Description'],
    [
        ['/',              'GET',  'Redirect to /issues'],
        ['/issues',        'GET',  'Issue log: HTML table of all issues, filterable by status / woreda / period. Conversation thread expandable per row.'],
        ['/issues/<id>',   'GET',  'Detail view: full SMS thread for one issue, DHIS2 data element values, timeline of state changes.'],
        ['/webhook/sms',   'POST', 'Twilio inbound SMS webhook. Validates Twilio signature, routes reply to state machine.'],
        ['/api/status',    'GET',  'JSON health check: uptime, open issue count, last successful poll timestamp, last error.'],
    ]
)
sp()

# ── 10. APScheduler Jobs ──────────────────────────────────────────────────────
h1('10. APScheduler Jobs')
body('APScheduler (BackgroundScheduler) runs inside the Flask process. All times East Africa Time (UTC+3). Jobs are idempotent — restarting the container does not create duplicate issues or duplicate SMS messages.')
sp()
tbl(
    ['Job ID', 'Schedule', 'What it does'],
    [
        ['poll_dhis2',
         'Every 5 minutes',
         'Runs outlier detection and DTP validation checks for current and prior period. Creates new issues for new violations. Deduplicates against open issues.'],
        ['check_missing_reports',
         'Daily at 08:00 EAT (from day 5 of month)',
         'Queries completeDataSetRegistrations for prior month. Flags facilities with no registration. Skips if prior to day 5.'],
        ['process_timers',
         'Every 30 minutes',
         'Scans open issues: sends retry SMS if 24h elapsed and retry_count < 3; escalates to next cascade level if 72h elapsed at current level; escalates zone→region→national on weekly cadence.'],
        ['monthly_summary',
         '1st of month at 09:00 EAT',
         'Sends digest of all unresolved issues from prior month to national TWG contact. Includes count by woreda and issue type.'],
    ]
)
sp()

# ── 11. Docker Compose Deployment ─────────────────────────────────────────────
h1('11. Docker Compose Deployment')
body('The agent is added as a fourth service to docker-compose.yml alongside the existing db, web (DHIS2), and any future services. Both the agent and DHIS2 containers share the same Docker bridge network; the agent reaches DHIS2 at http://web:8080/api (internal DNS), not localhost.')
sp()
mono(
    '# Addition to docker-compose.yml\n'
    '  agent:\n'
    '    build: ./agent              # Dockerfile at ./agent/Dockerfile\n'
    '    ports:\n'
    '      - "5001:5001"\n'
    '    volumes:\n'
    '      - ./agent/db:/data        # SQLite file persisted to host filesystem\n'
    '      - ./agent/contacts.csv:/app/contacts.csv  # contact registry (read-only)\n'
    '    environment:\n'
    '      DHIS2_BASE_URL:       http://web:8080/api\n'
    '      AGENT_USER:           ${AGENT_USER}\n'
    '      AGENT_PASS:           ${AGENT_PASS}\n'
    '      CLAUDE_API_KEY:       ${CLAUDE_API_KEY}\n'
    '      TWILIO_ACCOUNT_SID:   ${TWILIO_ACCOUNT_SID}\n'
    '      TWILIO_AUTH_TOKEN:    ${TWILIO_AUTH_TOKEN}\n'
    '      TWILIO_FROM_NUMBER:   ${TWILIO_FROM_NUMBER}\n'
    '      OUTLIER_THRESHOLD:    3.0\n'
    '      POLL_INTERVAL_MIN:    5\n'
    '      MISSING_REPORT_DAY:   5\n'
    '    depends_on:\n'
    '      - web\n'
    '    restart: unless-stopped\n'
    '\n'
    '# Agent Dockerfile (./agent/Dockerfile)\n'
    '  FROM python:3.12-slim\n'
    '  WORKDIR /app\n'
    '  COPY requirements.txt .\n'
    '  RUN pip install -r requirements.txt\n'
    '  COPY . .\n'
    '  CMD ["python", "agent.py"]'
)
sp()

# ── 12. Environment Variables ─────────────────────────────────────────────────
h1('12. Environment Variables')
body('All secrets and configurable parameters live in .env in the project root. Both the setup scripts and the agent container read from this file at startup.')
sp()
tbl(
    ['Variable', 'Used by', 'Description'],
    [
        ['DHIS2_BASE_URL',       'Setup scripts, Agent', 'http://localhost:8080/api (setup) or http://web:8080/api (Docker runtime)'],
        ['DHIS2_ADMIN_USER',     'Setup scripts only',   'DHIS2 admin username for phases 2–5 setup'],
        ['DHIS2_ADMIN_PASS',     'Setup scripts only',   'DHIS2 admin password'],
        ['DHIS2_USER_PASSWORD',  'Setup scripts only',   'Shared password for all demo role-based user accounts'],
        ['AGENT_USER',           'Agent',                'DHIS2 agent_service username'],
        ['AGENT_PASS',           'Agent',                'DHIS2 agent_service password'],
        ['CLAUDE_API_KEY',       'Agent',                'Anthropic API key'],
        ['TWILIO_ACCOUNT_SID',   'Agent',                'Twilio account SID'],
        ['TWILIO_AUTH_TOKEN',    'Agent',                'Twilio auth token'],
        ['TWILIO_FROM_NUMBER',   'Agent',                'Twilio sending phone number (E.164 format)'],
        ['OUTLIER_THRESHOLD',    'Agent',                'Z-score threshold for outlier detection (default: 3.0)'],
        ['POLL_INTERVAL_MIN',    'Agent',                'DQ check poll interval in minutes (default: 5)'],
        ['MISSING_REPORT_DAY',   'Agent',                'Day of month to start missing report checks (default: 5)'],
        ['POSTGRES_DB',          'docker-compose.yml',   'PostgreSQL database name (DHIS2 only)'],
        ['POSTGRES_USER',        'docker-compose.yml',   'PostgreSQL username'],
        ['POSTGRES_PASSWORD',    'docker-compose.yml',   'PostgreSQL password'],
    ]
)
sp()

# ── 13. End-to-End Walkthrough ────────────────────────────────────────────────
h1('13. End-to-End Walkthrough: Outlier Scenario')
body('Limalimo Health Post (Janamora Woreda) submits EPI data for April 2026 with BCG under-1 = 350. Normal range for a health post is 30–45. The following traces the full agent lifecycle.')
sp()
mono(
    'T+0:00  Facility worker submits form in DHIS2 (as any authenticated DHIS2 user)\n'
    '         Data lands in datavalue table immediately\n'
    '\n'
    'T+0:05  poll_dhis2 job fires\n'
    '  → GET /api/outlierDetection?... → Limalimo HP, BCG <1yr, value=350, z=8.4\n'
    '  → dedup check: no open issue for (PunEEFHArGE, 202604, outlier, WSy7zOZx1Wl)\n'
    '  → INSERT INTO issues (id=\'DQ-AX42\', status=\'notified\', ...)\n'
    '  → SELECT phone FROM contacts WHERE org_unit_uid=\'PunEEFHArGE\' AND level=5\n'
    '  → POST Twilio → SMS sent to facility worker\n'
    '  → INSERT INTO conversations (direction=\'outbound\', body=\'[DQ-AX42] ...\')\n'
    '\n'
    'T+2:14  Worker replies: "no wait, should be 53"\n'
    '  → Twilio → POST /webhook/sms (From=+251..., Body="no wait, should be 53")\n'
    '  → regex: no ref ID in body → check if From has one open issue → DQ-AX42\n'
    '  → Claude parse: {"intent": "correct", "value": 53}\n'
    '  → UPDATE issues SET status=\'awaiting_confirm\', proposed_value=\'53\'\n'
    '  → Send SMS: "[DQ-AX42] Confirm: BCG under-1 at Limalimo HP Apr 2026: 350→53. YES to apply."\n'
    '  → INSERT INTO conversations (direction=\'inbound\', ...)\n'
    '  → INSERT INTO conversations (direction=\'outbound\', ...)\n'
    '\n'
    'T+2:15  Worker replies: "YES"\n'
    '  → POST /api/dataValueSets (as agent_service) → DHIS2 returns 200\n'
    '  → UPDATE issues SET status=\'resolved\', resolved_value=\'53\', resolved_at=now()\n'
    '  → Send SMS: "[DQ-AX42] Done. BCG under-1 updated to 53. Issue closed."\n'
    '  → Re-run outlier check for Limalimo HP / 202604 → no violations returned\n'
    '\n'
    'T+2:16  Issue DQ-AX42 visible in /issues page as Resolved'
)
sp()

doc.save('AHEAD_AI_Tech_Architecture.docx')
print('Saved: AHEAD_AI_Tech_Architecture.docx')
