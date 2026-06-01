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

# ── 6. Issue Log Web Page ─────────────────────────────────────────────────────
h1('6. Issue Log Web Page')
body('A standalone Flask-served HTML page at port 5001. Intended for the AHEAD team and supervisors who want a real-time view of all issues without logging into DHIS2. The page reads from the agent\'s SQLite database, not from DHIS2.')
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

doc.save('AHEAD_AI_UX_Workflow.docx')
print('Saved: AHEAD_AI_UX_Workflow.docx')
