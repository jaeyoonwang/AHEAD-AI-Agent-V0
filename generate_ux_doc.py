#!/usr/bin/env python3
"""Generates AHEAD_AI_UX_Workflow.docx — UX and workflow specification.
Run: pip install python-docx && python3 generate_ux_doc.py
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
title = doc.add_heading('AHEAD AI Agent — UX & Workflow Specification', 0)
title.alignment = WD_ALIGN_PARAGRAPH.LEFT
title.runs[0].font.color.rgb = RGBColor(0x1F, 0x3A, 0x6E)
title.runs[0].font.size = Pt(18)
sub = doc.add_paragraph('SMS Notification Design, Escalation Logic, and Issue Log  |  UNICEF AHEAD × Gates Foundation AI Fellows  |  June 2026')
sub.runs[0].font.size = Pt(9); sub.runs[0].font.color.rgb = RGBColor(0x88, 0x88, 0x88); sub.runs[0].italic = True
sp()

# ── 1. User Roles ─────────────────────────────────────────────────────────────
h1('1. User Roles and Notification Scope')
body('Six roles exist in the AHEAD hierarchy. For MVP, only facility workers and woreda HMIS officers receive active SMS notifications. Zone, regional, and national staff receive escalation summaries only when issues remain unresolved at lower levels. The AHEAD/UNICEF team monitors everything passively via the issue log web page.')
sp()
tbl(
    ['Role', 'Notification channel', 'What they receive', 'MVP scope'],
    [
        ['Facility worker',
         'SMS (individual)',
         'One SMS per issue with a reference ID; confirmation loop; resolution confirmation',
         'Active — first point of contact for every issue'],
        ['Woreda HMIS officer',
         'SMS (summary)',
         'Batched summary of all unresolved issues in their woreda after 72h',
         'Active — escalation target'],
        ['Zone officer',
         'SMS (summary)',
         'Summary of unresolved issues across woredas after 1 week',
         'Active — escalation target'],
        ['Regional focal point',
         'SMS (summary)',
         'Summary of unresolved issues across zones after 1 further week',
         'Active — escalation target'],
        ['National TWG',
         'SMS (monthly digest)',
         'End-of-month summary of all unresolved issues across Ethiopia',
         'Active — monthly digest only'],
        ['UNICEF / AHEAD team',
         'Issue log web page',
         'Real-time view of all issues, statuses, and full SMS threads',
         'Passive — observe and intervene via log page'],
    ]
)
sp()
body('Important distinction: the notification contacts (phone numbers) are stored in the agent\'s own contact registry, not in DHIS2 user accounts. DHIS2 user accounts control data-entry access. The contact registry controls who gets notified. These are maintained separately.')
sp()
body('Demo focus: The live demonstration centres entirely on the facility-level health worker — the person who receives the initial SMS, engages in the correction conversation, and sees their submission corrected in DHIS2. The escalation cascade (woreda → zone → region → national) is part of the production architecture and fires automatically in the background, but is not walked through in the demo. The AHEAD team monitors everything via the standalone issue log web app shown at the end of the demo.')
sp()

# ── 2. Notification Triggers ──────────────────────────────────────────────────
h1('2. Notification Triggers')
tbl(
    ['Issue type', 'What causes it', 'Detection timing', 'Who is notified first'],
    [
        ['Statistical outlier',
         'A submitted value is flagged by DHIS2 outlier detection (Z-score >= 3.0 vs. facility historical baseline)',
         'Within 5 minutes of form submission',
         'Facility worker'],
        ['DTP1/DTP3 inconsistency',
         'Penta3 doses exceed Penta1 doses for same facility-period (biologically implausible)',
         'Within 5 minutes of form submission',
         'Facility worker'],
        ['Missing report',
         'Facility has no completed dataset registration by day 5 of the following month',
         'Daily at 8am, starting day 5 of following month',
         'Facility worker'],
    ]
)
sp()

# ── 3. Message Templates ──────────────────────────────────────────────────────
h1('3. SMS Message Templates')
body('All outbound messages are generated by Claude (claude-haiku-4-5) using a template as a prompt baseline. The reference ID appears in every message. Messages are kept under 160 characters where possible to avoid multi-part SMS charges, though clarity takes priority over length.')
sp()

h2('3.1  Initial notification — statistical outlier')
mono(
    '[DQ-AX42] Limalimo HP, Apr 2026\n'
    'BCG under-1: 350 reported\n'
    'Normal range: 30-45 (~10x high)\n'
    'Data entry error?\n'
    'Reply with correct value or KEEP to leave as-is.'
)
sp()

h2('3.2  Initial notification — DTP1/DTP3 inconsistency')
mono(
    '[DQ-BK19] Adi Goshu HP, Apr 2026\n'
    'Penta3 under-1: 80\n'
    'Penta1 under-1: 45\n'
    '3rd dose cannot exceed 1st dose.\n'
    'Reply with correct Penta3 value or KEEP to leave as-is.'
)
sp()

h2('3.3  Initial notification — missing report')
mono(
    '[DQ-MN33] Bichena HP\n'
    'No EPI report received for Apr 2026.\n'
    'Expected by May 5.\n'
    'Reply DONE if already submitted,\n'
    'or LATER if submitting this week.'
)
sp()

h2('3.4  Confirmation request (after worker gives a value)')
mono(
    '[DQ-AX42] Confirm change:\n'
    'Limalimo HP, Apr 2026\n'
    'BCG under-1: 350 -> 53\n'
    'Reply YES to apply or NO to cancel.'
)
sp()

h2('3.5  Resolved — correction applied')
mono(
    '[DQ-AX42] Done.\n'
    'BCG under-1 updated to 53 at Limalimo HP.\n'
    'Issue closed. Thank you.'
)
sp()

h2('3.6  Dismissed — value left unchanged')
mono(
    '[DQ-AX42] Noted.\n'
    'BCG under-1 left as 350 - recorded as reviewed.\n'
    'Issue closed.'
)
sp()

h2('3.7  Retry (24h no reply — sent up to 3 times)')
mono(
    '[DQ-AX42] Reminder (2 of 3):\n'
    'Limalimo HP, Apr 2026\n'
    'BCG under-1 = 350\n'
    'Please reply with the correct value or KEEP.'
)
sp()

h2('3.8  Woreda escalation summary')
body('Sent to the woreda HMIS officer after 72h of no facility-level resolution. One SMS covers all unresolved issues in that woreda from the same period.')
mono(
    '[DQ-WOREDA] Addi Arekay Woreda\n'
    '3 unresolved issues, Apr 2026:\n'
    'DQ-AX42 Limalimo HP: BCG outlier (3 days)\n'
    'DQ-BK19 Adi Goshu HP: Penta3 > Penta1 (3 days)\n'
    'DQ-MN33 Bichena HP: no report submitted\n'
    'Details: <issue log URL>'
)
sp()

h2('3.9  Monthly national digest')
body('Sent to the national TWG contact on the first of each month for all issues from the prior month that remain unresolved.')
mono(
    '[DQ-MONTHLY] Apr 2026 Summary\n'
    'Ethiopia: 3 issues still open\n'
    'Amhara / N. Gondar:\n'
    '  - 1 missing report (Bichena HP)\n'
    '  - 1 outlier (Limalimo HP, 25 days)\n'
    '  - 1 DTP inconsistency (Adi Goshu HP)\n'
    'View all: <issue log URL>'
)
sp()

# ── 4. Conversation Flows ─────────────────────────────────────────────────────
h1('4. Conversation Flows')

h2('4.1  Happy path — facility corrects on first reply')
mono(
    'Agent     [DQ-AX42] Limalimo HP, Apr 2026. BCG under-1: 350 (10x high).\n'
    '          Reply with correct value or KEEP.\n'
    '\n'
    'Facility  35\n'
    '\n'
    'Agent     [DQ-AX42] Confirm: BCG under-1 at Limalimo HP Apr 2026: 350 -> 35.\n'
    '          Reply YES to apply or NO to cancel.\n'
    '\n'
    'Facility  YES\n'
    '\n'
    'Agent     [DQ-AX42] Done. BCG under-1 updated to 35. Issue closed.'
)
sp()

h2('4.2  Worker gives wrong value then corrects mid-conversation')
body('The agent does not lock in a proposed value after one reply. If the worker sends a different number at the confirmation step, the agent updates the proposal and asks again. Claude detects that "no wait, should be 53" means intent=correct, value=53.')
mono(
    'Agent     [DQ-AX42] Limalimo HP, Apr 2026. BCG under-1: 350.\n'
    '          Reply with correct value or KEEP.\n'
    '\n'
    'Facility  35\n'
    '\n'
    'Agent     [DQ-AX42] Confirm: 350 -> 35. Reply YES or NO.\n'
    '\n'
    'Facility  no wait, should be 53\n'
    '\n'
    'Agent     [DQ-AX42] Got it - so correct value is 53?\n'
    '          Reply YES to apply 53 or send the correct number.\n'
    '\n'
    'Facility  YES\n'
    '\n'
    'Agent     [DQ-AX42] Done. BCG under-1 updated to 53. Issue closed.'
)
sp()

h2('4.3  Worker dismisses the flag (value is correct)')
mono(
    'Agent     [DQ-AX42] Limalimo HP, Apr 2026. BCG under-1: 350 (10x high).\n'
    '          Reply with correct value or KEEP to leave as-is.\n'
    '\n'
    'Facility  KEEP\n'
    '\n'
    'Agent     [DQ-AX42] Noted. Value left as 350 - recorded as reviewed.\n'
    '          Issue closed.'
)
sp()

h2('4.4  No reply — retry then escalation')
mono(
    'Day 0     Agent sends initial SMS\n'
    '\n'
    'Day 1     No reply after 24h\n'
    '          Agent sends Retry 1: "[DQ-AX42] Reminder (1 of 3): ..."\n'
    '\n'
    'Day 2     No reply after 24h\n'
    '          Agent sends Retry 2: "[DQ-AX42] Reminder (2 of 3): ..."\n'
    '\n'
    'Day 3     No reply after 24h\n'
    '          Agent sends Retry 3: "[DQ-AX42] Reminder (3 of 3): ..."\n'
    '          Agent escalates: cascade_level = 2 (woreda)\n'
    '          Woreda HMIS officer receives summary SMS\n'
    '\n'
    'Day 10    If still unresolved: escalate to zone (cascade_level = 3)\n'
    'Day 17    If still unresolved: escalate to region (cascade_level = 4)\n'
    'Month end All open issues appear in national monthly digest'
)
sp()

h2('4.5  Missing report — facility already submitted')
body('Occasionally a facility has submitted but the registration has not propagated in DHIS2 yet. The DONE reply triggers a re-check within the hour rather than immediately closing the issue.')
mono(
    'Agent     [DQ-MN33] Bichena HP. No EPI report received for Apr 2026.\n'
    '          Reply DONE if submitted, or LATER if submitting this week.\n'
    '\n'
    'Facility  DONE\n'
    '\n'
    'Agent     [DQ-MN33] Thanks - we will re-check within the hour.\n'
    '          If your submission is confirmed, the issue will close automatically.\n'
    '\n'
    '          [One hour later — poll_dhis2 finds the registration]\n'
    '\n'
    'Agent     [DQ-MN33] Confirmed. Bichena HP Apr 2026 report received.\n'
    '          Issue closed.'
)
sp()
body('If the re-check still finds no registration after 1 hour, the issue remains open and the next retry timer applies as normal.')
sp()

# ── 5. Escalation Timeline ────────────────────────────────────────────────────
h1('5. Escalation Timeline')
body('The timeline below shows a single issue from detection to national digest, assuming no resolution at any level.')
sp()
mono(
    'Day 0    Issue detected → facility worker notified (SMS)\n'
    '         ├── Facility replies → confirmation loop → resolved (ideal path)\n'
    '         └── No reply...\n'
    '\n'
    'Day 1    Retry 1 of 3 (24h after initial)\n'
    'Day 2    Retry 2 of 3 (48h after initial)\n'
    'Day 3    Retry 3 of 3 + escalate to woreda HMIS officer\n'
    '         ├── Woreda intervenes → resolved\n'
    '         └── No resolution...\n'
    '\n'
    'Day 10   Escalate to zone officer (1 week after woreda notification)\n'
    '         ├── Zone intervenes → resolved\n'
    '         └── No resolution...\n'
    '\n'
    'Day 17   Escalate to regional focal point (1 week after zone notification)\n'
    '         └── No resolution...\n'
    '\n'
    'Month end  National TWG receives monthly digest (includes this issue)'
)
sp()
body('Escalation messages at woreda level and above are sent as a single summary SMS covering all unresolved issues from that org unit in the same period — not one SMS per issue. This prevents notification fatigue at higher levels where one officer may receive reports from many facilities.')
sp()

# ── 6. Issue Log Web App ──────────────────────────────────────────────────────
h1('6. Issue Log Web App (Standalone)')
body('A standalone web application at http://localhost:5001, completely separate from DHIS2. No DHIS2 login required. It reads from the agent\'s own SQLite database and is the primary monitoring surface for the AHEAD team and supervisors. Every issue the agent detects, every SMS sent and received, and every state change is visible here in real-time.')
sp()

h2('Page layout (wireframe)')
mono(
    'AHEAD Data Issue Log                      [ Open: 2 | Resolved: 47 | All: 49 ]\n'
    'Filter: [ All types v ]  [ All woredas v ]  [ Apr 2026 v ]  [ Search ref ID... ]\n'
    '--------------------------------------------------------------------------------\n'
    'Ref     Facility          Issue              Period  Status    Opened      Updated\n'
    '--------------------------------------------------------------------------------\n'
    'DQ-AX42 Limalimo HP       Outlier: BCG 350   202604  OPEN      2026-05-01  05-01\n'
    'DQ-BK19 Adi Goshu HP      DTP3 > DTP1        202604  OPEN      2026-05-01  05-01\n'
    'DQ-MN33 Bichena HP        Missing report     202604  ESCALATED 2026-05-01  05-04\n'
    '[> expand] Full SMS thread for DQ-MN33:\n'
    '  2026-05-01 08:06  OUT  [DQ-MN33] Bichena HP. No EPI report...\n'
    '  2026-05-02 08:06  OUT  [DQ-MN33] Reminder (1 of 3)...\n'
    '  2026-05-03 08:06  OUT  [DQ-MN33] Reminder (2 of 3)...\n'
    '  2026-05-04 08:06  OUT  [DQ-MN33] Reminder (3 of 3)...\n'
    '  2026-05-04 08:07  OUT  Woreda summary sent to Bekele Haile\n'
    '--------------------------------------------------------------------------------'
)
sp()

h2('Issue log columns')
tbl(
    ['Column', 'Content'],
    [
        ['Ref ID',          'e.g. DQ-AX42 — unique across all issues, never reused'],
        ['Facility',        'Facility name and woreda in parentheses'],
        ['Issue type',      'Outlier (element + value), DTP3 > DTP1, or Missing report'],
        ['Period',          'DHIS2 period code, displayed as human-readable month (Apr 2026)'],
        ['Status',          'OPEN | AWAITING CONFIRM | RESOLVED | DISMISSED | ESCALATED'],
        ['Cascade level',   'Current level: Facility / Woreda / Zone / Region / National'],
        ['Opened',          'Timestamp when issue was first detected'],
        ['Last contact',    'Timestamp of last outbound SMS'],
        ['Resolved value',  'What the value was corrected to (blank if not yet resolved)'],
        ['[Expand]',        'Click to see the full SMS thread for that issue'],
    ]
)
sp()

h2('Filters')
tbl(
    ['Filter', 'Options'],
    [
        ['Status',   'All / Open / Escalated / Resolved / Dismissed'],
        ['Type',     'All / Outlier / DTP inconsistency / Missing report'],
        ['Woreda',   'All / [woreda names from org unit hierarchy]'],
        ['Period',   'All / [YYYYMM dropdown]'],
        ['Search',   'Free-text search on ref ID or facility name'],
    ]
)
sp()

# ── 7. Edge Cases ─────────────────────────────────────────────────────────────
h1('7. Edge Cases and Agent Behaviour')
tbl(
    ['Edge case', 'Agent behaviour'],
    [
        ['Inbound SMS contains no reference ID',
         'Agent checks if the sender\'s phone number has exactly one open issue. If yes, routes to that issue. If multiple open issues, replies: "Please include your issue ref ID (e.g. DQ-AX42) so we can route your reply."'],
        ['Reference ID not found or already closed',
         'Agent replies: "Ref ID not recognised or issue already closed. View all issues at <issue log URL>."'],
        ['Worker replies with non-numeric text for an outlier issue',
         'Claude returns intent=unknown. Agent replies: "Please reply with a number (the correct value) or KEEP to leave as-is."'],
        ['Worker sends a value that still looks like an outlier',
         'Agent applies the confirmed value as requested, then re-runs DQ checks in the next poll cycle. If the new value still fails, a new issue is created with a new ref ID.'],
        ['Same facility has two open issues simultaneously',
         'Both have distinct ref IDs. Every outbound message includes the ref ID. Worker must include the ref ID in replies — if missing, agent uses the single-open-issue routing logic above.'],
        ['Correction POST to DHIS2 fails (DHIS2 down or network error)',
         'Agent sends SMS: "Could not apply the change right now. Please re-enter the value directly in DHIS2 and reply DONE once submitted." Issue status remains awaiting_confirm. Retry flagged for next cycle.'],
        ['Worker replies DONE (missing report already submitted)',
         'Agent schedules a re-check in 1 hour via APScheduler. If the registration appears, issue closes automatically with a confirmation SMS. If not, issue remains open.'],
        ['Escalation notification itself fails to deliver',
         'Twilio delivery failure is logged. Agent retries the escalation SMS once after 30 minutes. Failure is visible on the issue log page under last_contact.'],
        ['Issue resolved at woreda level (not facility)',
         'If woreda officer contacts AHEAD team directly and they manually close the issue via the log page, status is set to resolved with a note. No further SMS is sent.'],
    ]
)
sp()

# ── 8. Reference ID Design ────────────────────────────────────────────────────
h1('8. Reference ID Design')
body('Every issue gets a unique ID on creation. The ID appears in every outbound message and is how the agent routes inbound replies to the right issue. Design constraints:')
sp()
bullet('Visually unambiguous when read aloud or off a small phone screen')
bullet('Short enough to quote in an SMS without taking up too much space')
bullet('Random enough to be hard to guess (prevents spoofed replies)')
bullet('Never reused — resolved issues keep their ID permanently for audit')
sp()
tbl(
    ['Property', 'Decision', 'Reason'],
    [
        ['Format', 'DQ-XXXX (4-character suffix)', 'DQ prefix identifies the source system; 4 chars is short and unambiguous'],
        ['Character set',
         'A B C D E F G H J K M N P Q R S T U V W X Y + 3 4 5 6 7 8 9 (29 chars)',
         'Excludes 0/O, 1/I/L, 2/Z — characters that look alike on paper or screen'],
        ['Capacity', '29^4 = 707,281 unique IDs', 'More than sufficient for MVP; Phase 2 can extend to 5 chars if needed'],
        ['Generation', 'Python secrets.choice() from the charset', 'Cryptographically random — hard to guess or enumerate'],
        ['Collision check', 'DB lookup before issuing', 'Probability of collision is < 0.001% even at 10,000 open issues'],
    ]
)
sp()

# ── 9. MVP vs Phase 2 Scope ───────────────────────────────────────────────────
h1('9. MVP vs Phase 2 Scope')
body('The following table clarifies what is in scope for this build and what is explicitly deferred. Phase 2 items are excluded not because they are unimportant but because they either require external dependencies (Meta WhatsApp approval, DHIS2 App Framework expertise) or can be validated after the core SMS loop is working.')
sp()
tbl(
    ['Feature', 'MVP', 'Phase 2', 'Notes'],
    [
        ['Post-commit DQ checks (polling)',                     'Yes', '—',  ''],
        ['Outlier detection (DHIS2 built-in, Z-score)',         'Yes', '—',  ''],
        ['DTP1/DTP3 consistency (DHIS2 validation rules)',      'Yes', '—',  ''],
        ['Missing report detection',                            'Yes', '—',  ''],
        ['Two-way SMS conversation with confirmation loop',     'Yes', '—',  ''],
        ['Full escalation cascade (facility → national)',       'Yes', '—',  ''],
        ['Apply corrections back to DHIS2 via API',            'Yes', '—',  ''],
        ['Issue log web page (standalone Flask)',               'Yes', '—',  ''],
        ['Claude API (reply parsing + message generation)',     'Yes', '—',  ''],
        ['English-language messages only',                      'Yes', '—',  ''],
        ['5-method outlier ensemble (R script integration)',    '—',  'Yes', 'Requires access to AHEAD R scripts; deferred'],
        ['Name consistency check',                              '—',  'Yes', 'Not covered by DHIS2 built-in rules'],
        ['WhatsApp channel',                                    '—',  'Yes', 'Requires Meta Business API approval (1-4 weeks)'],
        ['Email channel',                                       '—',  'Yes', 'Reply parsing noisier; lower priority'],
        ['Pre-commit inline form warning (custom form JS)',     '—',  'Yes', 'Requires DHIS2 custom form; useful but not needed to validate cascade'],
        ['Amharic messages',                                    '—',  'Yes', 'Claude can generate; need translation review before sending'],
        ['DHIS2 embedded app (issue log inside DHIS2)',        '—',  'Yes', 'Requires DHIS2 App Framework (React); standalone page sufficient for MVP'],
        ['Inbound phone call routing',                          '—',  'Yes', 'Higher complexity; SMS covers facility workers adequately for MVP'],
    ]
)
sp()

# ── 10. Demo Script ───────────────────────────────────────────────────────────
h1('10. Demo Script')
body('Four demos covering each seeded DQ issue type, followed by the issue log overview. Total runtime: 14-18 minutes. Each demo follows the same arc: show the raw issue in DHIS2, trigger the agent, run the SMS conversation on the presenter\'s phone, then show the correction applied in DHIS2 and the resolved state in the issue log. The primary persona throughout is the facility-level health worker.')
sp()

tbl(
    ['Demo', 'Issue type', 'Facility', 'Duration', 'What it proves'],
    [
        ['A', 'Statistical outlier',    'Limalimo Health Post',  '~5 min', 'Full SMS loop: detection → conversation → DHIS2 correction'],
        ['B', 'DTP1/DTP3 inconsistency','Adi Goshu Health Post', '~4 min', 'Validation rule violation → correction via SMS'],
        ['C', 'Missing report',         'Bichena Health Post',   '~3 min', 'Daily cron detection → notification → LATER/DONE reply'],
        ['D', 'Issue log web app',      '(all facilities)',      '~3 min', 'Supervisor view: all issues, statuses, and SMS threads'],
    ]
)
sp()

h2('Prerequisites — confirm before presenting')
bullet('DHIS2 running: http://localhost:8080 responds with login page')
bullet('Agent running: http://localhost:5001/api/status returns JSON with uptime')
bullet('inject_data.py has been run — three seeded issues exist for period 202604 (April 2026)')
bullet('contacts table in SQLite seeded with presenter\'s phone for: Limalimo HP, Adi Goshu HP, Bichena HP')
bullet('Presenter\'s phone visible to audience (screen mirror or camera pointing at phone)')
bullet('Twilio account active and TWILIO_FROM_NUMBER configured in .env')
sp()
body('To trigger an immediate DQ check without waiting 5 minutes: POST http://localhost:5001/api/scan. This fires all three checks instantly and is the recommended way to trigger detections during the demo.')
sp()

h2('Demo A — Statistical Outlier: Limalimo Health Post (~5 min)')
body('What this shows: The agent detects a value that is ~10x the expected range for that facility type, sends an SMS with a reference ID, and applies the confirmed correction directly to DHIS2.')
sp()

body('Step 1 — Show the issue in DHIS2 (1 min)')
bullet('Log in at http://localhost:8080 as admin / [DHIS2_ADMIN_PASS from .env]')
bullet('Open Data Entry (grid icon in top menu)')
bullet('Navigate in the left org unit tree: Ethiopia → Amhara → North Gondar → Janamora Woreda → Limalimo Health Post')
bullet('Select dataset: EPI - Routine vaccine delivery | Period: April 2026')
bullet('Point out: BCG < 1 year = 350. For a health post, the normal range is 30-45. This is ~10x the expected maximum.')
sp()

body('Step 2 — Trigger the agent (30 sec)')
bullet('In a terminal or browser: POST http://localhost:5001/api/scan')
bullet('Alternatively: curl -s -X POST http://localhost:5001/api/scan')
bullet('The agent runs outlier detection and creates issue DQ-XXXX for Limalimo HP')
bullet('Navigate to http://localhost:5001/issues — the new issue appears as OPEN')
sp()

body('Step 3 — Receive the SMS')
bullet('Presenter\'s phone receives:')
mono(
    '[DQ-XXXX] Limalimo HP, Apr 2026\n'
    'BCG under-1: 350 reported\n'
    'Normal range: 30-45 (~10x high)\n'
    'Data entry error?\n'
    'Reply with correct value or KEEP to leave as-is.'
)
bullet('Point out to audience: the reference ID, the specific data element named, the normal range given, the clear call to action')
sp()

body('Step 4 — Reply with the corrected value')
bullet('Reply to the SMS: 35')
bullet('Agent receives the reply, Claude parses it as intent=correct, value=35')
bullet('Agent sends confirmation:')
mono(
    '[DQ-XXXX] Confirm change:\n'
    'Limalimo HP, Apr 2026\n'
    'BCG under-1: 350 -> 35\n'
    'Reply YES to apply or NO to cancel.'
)
sp()

body('Step 5 — Confirm')
bullet('Reply to the SMS: YES')
bullet('Agent writes value=35 to DHIS2 via POST /api/dataValueSets (as agent_service)')
bullet('Agent sends:')
mono(
    '[DQ-XXXX] Done.\n'
    'BCG under-1 updated to 35 at Limalimo HP.\n'
    'Issue closed. Thank you.'
)
sp()

body('Step 6 — Show correction in DHIS2')
bullet('Switch back to the DHIS2 browser tab')
bullet('Refresh the data entry form for Limalimo HP / April 2026')
bullet('BCG < 1 year now shows 35 (was 350)')
bullet('Optional: open DHIS2 audit log to show the change was made by agent_service, not a human')
sp()

body('Step 7 — Show issue log')
bullet('Switch to http://localhost:5001/issues')
bullet('Issue DQ-XXXX shows status: RESOLVED, with resolved value 35')
bullet('Click to expand the full SMS thread — 5 messages visible: initial, "35", confirmation, "YES", closure')
sp()

body('Expected final state after Demo A:')
bullet('DHIS2: Limalimo HP, Apr 2026, BCG < 1 year = 35 (was 350)')
bullet('Issue log: DQ-XXXX | Outlier: BCG | Limalimo HP | RESOLVED | Corrected value: 35')
bullet('SMS thread: 5 messages (2 outbound, 2 inbound, 1 outbound closure)')
sp()

h2('Demo B — DTP1/DTP3 Inconsistency: Adi Goshu Health Post (~4 min)')
body('What this shows: The EPI metadata package\'s built-in validation rule (Penta3 <= Penta1) is violated. The agent detects it via /api/validationResults and notifies the facility worker.')
sp()

body('Step 1 — Show the issue in DHIS2')
bullet('Navigate to: North Gondar → Addi Arekay Woreda → Adi Goshu Health Post')
bullet('Dataset: EPI - Routine vaccine delivery | Period: April 2026')
bullet('Point out: DPT-HepB-HIB 1 (Penta1) < 1 year = 45 | DPT-HepB-HIB 3 (Penta3) < 1 year = 80')
bullet('Explain: the third dose of a vaccine series can never exceed the first dose — dropout only goes one direction. This is a transposition error.')
sp()

body('Step 2 — Trigger the agent')
bullet('POST http://localhost:5001/api/scan')
bullet('Agent triggers a DHIS2 validation run, reads the violation, creates a new issue')
bullet('http://localhost:5001/issues — new issue appears for Adi Goshu HP')
sp()

body('Step 3 — Receive the SMS')
mono(
    '[DQ-XXXX] Adi Goshu HP, Apr 2026\n'
    'Penta3 under-1: 80\n'
    'Penta1 under-1: 45\n'
    '3rd dose cannot exceed 1st dose.\n'
    'Reply with correct Penta3 value or KEEP.'
)
sp()

body('Step 4 — Reply and confirm')
bullet('Reply: 38 (a plausible Penta3 value — approximately 85% of Penta1=45, matching normal dropout)')
bullet('Agent confirms: "[DQ-XXXX] Confirm: Penta3 under-1 at Adi Goshu HP Apr 2026: 80 -> 38. Reply YES."')
bullet('Reply: YES')
bullet('Agent applies correction, sends closure SMS')
sp()

body('Step 5 — Show correction')
bullet('Refresh DHIS2: Penta3 < 1 year = 38 (was 80). Penta1 (45) now correctly exceeds Penta3 (38).')
bullet('Issue log: DQ-XXXX | DTP inconsistency | Adi Goshu HP | RESOLVED | Corrected value: 38')
sp()

body('Expected final state after Demo B:')
bullet('DHIS2: Adi Goshu HP, Apr 2026, Penta3 < 1 year = 38 (was 80)')
bullet('Issue log: DQ-XXXX | DTP3 > DTP1 | Adi Goshu HP | RESOLVED | Corrected value: 38')
bullet('SMS thread: 5 messages')
sp()

h2('Demo C — Missing Report: Bichena Health Post (~3 min)')
body('What this shows: The agent\'s daily missing report check fires and detects a facility that submitted no data for the period. Two reply paths are shown: LATER (still coming) and the optional DONE path (already submitted).')
sp()

body('Step 1 — Show the blank form in DHIS2')
bullet('Navigate to: North Gondar → Dabat Woreda → Bichena Health Post')
bullet('Dataset: EPI - Routine vaccine delivery | Period: April 2026')
bullet('The entire form is blank — no values in any field')
bullet('Explain: inject_data.py deliberately skipped this facility for April 2026 to simulate a facility that failed to submit its monthly report')
sp()

body('Step 2 — Trigger the missing report check')
bullet('POST http://localhost:5001/api/scan?check=missing_reports')
bullet('Agent queries completeDataSetRegistrations, finds Bichena HP absent for 202604')
bullet('New issue created: type=missing_report, facility=Bichena HP')
sp()

body('Step 3 — Receive the SMS')
mono(
    '[DQ-XXXX] Bichena HP\n'
    'No EPI report received for Apr 2026.\n'
    'Expected by May 5.\n'
    'Reply DONE if already submitted,\n'
    'or LATER if submitting this week.'
)
sp()

body('Step 4a — Reply path: LATER (primary demo path)')
bullet('Reply: LATER')
bullet('Agent sends:')
mono(
    '[DQ-XXXX] Noted. Please submit your Apr 2026\n'
    'EPI report when ready.\n'
    'We will follow up if not received by end of week.'
)
bullet('Issue remains OPEN in the log — the agent will retry and escalate if no submission arrives')
sp()

body('Step 4b — Reply path: DONE (optional extension)')
bullet('If you want to show the DONE flow: have the facility worker first submit data for Bichena HP in DHIS2 (as eth_woreda_01 or admin), then reply DONE')
bullet('Agent re-checks DHIS2 within the hour. If the registration now appears, it sends:')
mono(
    '[DQ-XXXX] Confirmed. Bichena HP Apr 2026\n'
    'report received. Issue closed.'
)
sp()

body('Expected final state after Demo C:')
bullet('DHIS2: Bichena HP, Apr 2026 — still blank (LATER path) or newly filled (DONE path)')
bullet('Issue log: DQ-XXXX | Missing report | Bichena HP | OPEN/NOTIFIED (LATER) or RESOLVED (DONE)')
bullet('SMS thread: 2 messages (notification + LATER acknowledgement)')
sp()

h2('Demo D — Issue Log Web App (~3 min)')
body('What this shows: The standalone supervisor view. The AHEAD team and George\'s team would use this to monitor all issues across the Ethiopia org unit hierarchy in real-time, without logging into DHIS2.')
sp()

body('Step 1 — Open the issue log')
bullet('Navigate to http://localhost:5001/issues in the browser')
bullet('Three issues visible: Demo A (RESOLVED), Demo B (RESOLVED), Demo C (OPEN or RESOLVED depending on path taken)')
sp()

body('Step 2 — Show filtering')
bullet('Use the Status filter: select "Open" — only Demo C issue remains visible')
bullet('Use the Status filter: select "Resolved" — only Demo A and B visible')
bullet('Use the Period filter: select "Apr 2026" — all three issues (confirms period scoping)')
sp()

body('Step 3 — Expand a conversation thread')
bullet('Click expand on Demo A (DQ-XXXX, Limalimo HP)')
bullet('Show the full SMS thread: timestamp, direction (IN/OUT), message body')
bullet('Point out: every message is logged, inbound and outbound, with exact timestamps')
bullet('This is the audit trail — if there is ever a dispute about what was agreed, the thread is the record')
sp()

body('Step 4 — Highlight the escalation indicator (if applicable)')
bullet('If Demo C has been open for a while without resolution, the cascade_level column shows "Woreda" — the issue has been escalated')
bullet('Explain: this escalation happened automatically with no manual intervention')
sp()

body('Expected final state after Demo D:')
bullet('Issue log shows 3 issues: 2 Resolved (A, B), 1 Open or Resolved (C)')
bullet('Conversation threads visible and expandable for each')
bullet('Audience understands the page is the single source of truth for all DQ activity')
sp()

h2('Common demo questions and answers')
tbl(
    ['Question', 'Answer'],
    [
        ['What if the facility worker ignores the SMS?',
         'The agent retries every 24h for 3 days, then automatically sends a summary to the woreda HMIS officer. No manual follow-up needed from the AHEAD team.'],
        ['Who maintains the list of phone numbers?',
         'The AHEAD team maintains a contacts CSV that is loaded into the agent\'s database at startup. It maps each org unit to a phone number and is updated as staff change.'],
        ['Can the agent send messages in Amharic?',
         'Not in MVP — English only. Claude can generate Amharic messages and this is a straightforward Phase 2 upgrade, pending translation review.'],
        ['Does the facility worker need to install an app?',
         'No. All interaction is via standard SMS. Works on any phone, including basic feature phones without internet.'],
        ['What if the agent applies a wrong correction?',
         'The agent always asks for explicit YES confirmation before writing anything to DHIS2. The original value, proposed value, and final value are all logged in the issue thread for audit.'],
        ['What happens to issues that never get resolved?',
         'They escalate through the hierarchy (woreda → zone → region) and appear in the national monthly digest. They remain open and visible in the issue log indefinitely until manually closed.'],
    ]
)
sp()

doc.save('AHEAD_AI_UX_Workflow.docx')
print('Saved: AHEAD_AI_UX_Workflow.docx')
