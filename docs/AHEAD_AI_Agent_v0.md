# AHEAD AI Agent — V0 Reference

**Project:** UNICEF AHEAD × Gates Foundation AI Fellows  
**Scope:** Real-time immunization data quality monitoring, Ethiopia  
**Status:** Prototype fully implemented and tested end-to-end (June 2026)

---

## 1. What It Is

AHEAD is a UNICEF initiative that produces subnational immunization analytics by running data quality (DQ) checks on monthly facility data from DHIS2. Today this loop is manual: UNICEF HQ extracts data, runs checks in R, emails Excel files to country teams, waits for replies, applies corrections, and restarts. The full cycle takes days.

This agent replaces the email + Excel exchange with a real-time system. When a facility worker submits data in DHIS2, the agent detects issues within 30 seconds, sends a WhatsApp alert with the same numbered response options as the AHEAD Excel dropdowns, parses the reply, asks for confirmation, and writes the correction back to DHIS2 automatically. Everything is logged in a live web dashboard.

**What it replaces:** Flag detection at batch time → flag detection at entry time. Email + Excel → WhatsApp. Manual data corrections by HQ → automatic write-back.

---

## 2. Architecture

```
DHIS2 (port 8080)          Agent (port 5001)              Contacts
─────────────────    ←→    ─────────────────    ←→    ─────────────────
Facility submits           30s poll detects              Facility worker
  data via form            change → DQ scan              receives WhatsApp
                           → create issue                → replies 1-6
                           → send alert                  → agent confirms
                           → write correction            → YES/NO
                           → log to dashboard
```

| Component | File | What it does |
|---|---|---|
| Poll + scheduler | `agent/app.py` | Flask server + APScheduler jobs (30s poll, daily missing check, 30min escalation, monthly digest) |
| DQ engine | `agent/dq_engine.py` | Runs 3 checks; creates issue records |
| DHIS2 client | `agent/dhis2_client.py` | All API calls — poll, outlier Z-score, DTP fetch, write-back |
| SMS / WhatsApp | `agent/sms.py` | Twilio wrapper + message templates |
| Conversation state | `agent/state_machine.py` | Routes inbound replies; calls Claude to parse options; manages YES/NO confirmation |
| Database | `agent/db.py` | SQLite — `contacts`, `issues`, `conversations`, `org_unit_hierarchy`, `poll_state` |

**Third-party services:** Twilio WhatsApp (outbound alerts + inbound replies), Claude API `claude-haiku-4-5` (parses which numbered option the user selected — does NOT generate messages), ngrok (local tunnel for webhook in demo mode).

---

## 3. How To Run

### Prerequisites

| Requirement | Where |
|---|---|
| Docker Desktop (running) | docker.com |
| Python 3.x + `pip3 install -r requirements.txt` | — |
| Claude API key | console.anthropic.com |
| Twilio account + phone number | twilio.com |
| ngrok account + authtoken | ngrok.com |
| `.env` filled in (see `.env.example`) | project root |
| `config.py` copied from `config.example.py` | project root |

> DHIS2 sandbox setup (one-time): see `docs/dhis2_setup_guide.md` and `README.md`.

### Starting the agent

**One-time per phone:** Join the Twilio WhatsApp sandbox. Open WhatsApp, message **+1 415 523 8886** with your sandbox keyword (found at twilio.com/console → Messaging → Try it out).

**One-time per deployment:** Update the contact phone number in `agent/seed_contacts.py` → `build_contacts()`, then run:

```bash
python3 agent/seed_contacts.py --clear
```

**Each session:**

```bash
python3 agent/app.py
```

Startup output:

```
[APP] DHIS2 reachable — agent_service authenticated
[APP] poll cursor initialised to 2026-06-04T... (first run)
[APP] scheduler started — poll every 30s
[NGROK] *** set Twilio webhook → https://xxxx.ngrok-free.app/webhook/sms ***

  ┌──────────────────────────────────────────────────────────┐
  │  DHIS2               →  http://localhost:8080            │
  │  Issue log           →  http://localhost:5001/issues     │
  │  Health check        →  http://localhost:5001/api/health │
  └──────────────────────────────────────────────────────────┘
```

Copy the ngrok URL → paste into Twilio WhatsApp sandbox as the webhook ("When a message comes in"). Do this each session — the URL changes on restart.

### Before each demo: reset

While the agent is running, call:

```bash
curl -s -X POST http://localhost:5001/api/reset-demo
```

This does three things atomically: deletes all June 2026 data values from DHIS2 for Addi Arekay HC, clears the agent DB (issues, conversations), and advances the poll cursor to now. **No agent restart needed.** Refresh `localhost:5001/issues` and it will be empty.

> **Why DHIS2 data must be cleared:** DHIS2 does not update `lastUpdated` when you save the same value that's already stored. If BCG is already 970 and you type 970 again, DHIS2 silently skips the write — invisible to the poll. Clearing DHIS2 first ensures every demo entry is a genuine first write.

If you need to restart the agent (port conflict):

```bash
pkill -f "agent/app.py"; sleep 1 && python3 agent/app.py
```

---

## 4. The Three DQ Checks

All checks run in `agent/dq_engine.py`. Thresholds are in `config.py` — no code change needed to tune them.

---

### Check 1: Outlier Detection

**Trigger:** Fires within 30 seconds whenever new data values appear.

**How it works:**

1. Fetches ~2.5 years of raw data for all facilities from DHIS2 (`GET /api/dataValueSets`)
2. Groups values into per-facility, per-antigen time series
3. For each value, computes **leave-one-out Z-score**: excludes the candidate period from its own baseline so a bad value can't mask itself
4. Applies **scope filter**: discards old outliers — only flags values that were just submitted
5. Applies **absolute deviation filter**: skips values where `|value − mean| < 100 doses`, preventing false positives at small health posts where natural single-dose swings produce high Z-scores

**A value is flagged if BOTH conditions hold:**
- Z-score ≥ 2.0 SD from leave-one-out baseline (AHEAD guide Table 1, method 1)
- Absolute deviation > 100 doses (AHEAD guide Table 1, method 5)

**Why AND, not OR:** Health posts with mean BCG ≈ 2 doses naturally swing ±1 dose (Z ≈ 2.5). OR logic triggered 87 false positives in testing. AND ensures only genuinely large deviations are flagged. BCG=970 (abs_diff ≈ 870) passes both.

**Known limitation (masking):** If a historical error was never corrected, it pulls the mean toward itself, making the baseline less accurate and reducing sensitivity to new errors. Robust statistics (Median Absolute Deviation — method 3 of the AHEAD ensemble) are immune to this and are the top V1 priority.

**Example alert:**

```
AHEAD DQ Alert [DQ-XXXX]
Addi Arekay Health Center — Jun 2026
BCG (under 1 year): 970 doses (expected 79–114)

Reply with option number:
1. Replace with 6-month average
2. Keep as-is (no action)
3. Set to zero
4. Replace with specific value
5. At health facility doses only
6. Outreach doses only
```

**Example confirmation (option 4 — specific value):**

```
[DQ-XXXX] Confirm change:
BCG (under 1 year) — Addi Arekay Health Center (Jun 2026)
970 → 97

Reply YES to update DHIS2 or NO to choose again.
```

---

### Check 2: DTP1/DTP3 Consistency

**Trigger:** Fires within 30 seconds when new data values appear (same trigger as outlier).

**How it works:** Fetches Penta1 and Penta3 for each changed (facility, period) and tests:

```
relative gap = |Penta3 − Penta1| / Penta1
absolute gap = |Penta3 − Penta1|

Flag if: relative gap > 30%  OR  absolute gap > 100 doses
```

**Why OR:** The relative threshold catches percentage inconsistencies regardless of facility size. The absolute threshold catches large hospitals where even a smaller percentage gap represents hundreds of doses. Either signal is clinically implausible — DTP3 can never exceed DTP1 because every child completing the third dose must have received the first.

**Thresholds by data level (from AHEAD guide):**

| Level | Relative | Absolute |
|---|---|---|
| Monthly facility (current scope) | > 30% | > 100 doses |
| Monthly admin2 | > 20% | > 250 doses |
| Annual admin2 | > 15% | > 1,000 doses |

**Example alert (DTP1=60, DTP3=90):**

```
AHEAD DQ Alert [DQ-YYYY]
Addi Arekay Health Center — Jun 2026
DTP1 (under 1 year): 60 doses
DTP3 (under 1 year): 90 doses
(DTP3 > DTP1, gap: 50%)

Reply with option number:
1. Keep as-is (no action)
2. Use DTP1 value for both
3. Use DTP3 value for both
4. Replace with specific value
5. Other reason
```

**Example confirmation (option 2 — use DTP1 for both):**

```
[DQ-YYYY] Confirm change:
DTP3 (under 1 year) — Addi Arekay Health Center (Jun 2026)
90 → 60 (use DTP1 value for both)

Reply YES to update DHIS2 or NO to choose again.
```

---

### Check 3: Missing Reports

**Trigger:** Daily cron at 8am EAT, starting on day 10 of the following month (configurable via `MISSING_REPORT_START_DAY` in `config.py`).

**How it works:**

```
submitted  = facilities that clicked "Complete" in DHIS2 (completeDataSetRegistrations API)
expected   = all 12 facilities at level 5 under the root org unit
missing    = expected − submitted  →  one issue created per absent facility
```

**Design intent:** Catching an absence can't be event-driven — nothing is submitted when nothing is submitted. The day-10 delay matches the AHEAD guide's "recovery first" principle: give facilities time to submit normally before flagging.

**Limitation:** Only detects a fully absent submission. A form submitted with blank individual vaccine cells is not caught.

**Example alert:**

```
AHEAD DQ Alert [DQ-ZZZZ]
Addi Arekay Health Center — Jun 2026
Monthly EPI report not received.

Reply SUBMIT if already submitted, or:
1. Will submit by [date]
2. Data cannot be recovered
3. Facility closed / no service that month
4. Other reason
```

---

## 5. Response Options

Options match the AHEAD Excel dropdown schema (reference guide sections 2.2–2.4). Claude parses which number was selected; it does not generate the options.

**All options that modify DHIS2 data require a YES/NO confirmation before being applied.** On NO, the original options are re-sent.

**All written values are rounded to the nearest integer.** DHIS2 rejects decimal values for dose data elements. This applies to every write-back path — user-provided values (e.g. "97"), computed values (e.g. a 6-month average of 99.5 → written as 100), and DTP set-both corrections. The rounding happens in `_execute_write_back()` in `agent/state_machine.py` before the DHIS2 API call.

| Check | # | Option | What happens |
|---|---|---|---|
| Outlier | 1 | Replace with 6-month average | Agent computes avg of 3 periods before + 3 after; shows value in confirmation; writes on YES |
| Outlier | 2 | Keep as-is | Closes issue, no data change |
| Outlier | 3 | Set to zero | Confirms then writes 0 |
| Outlier | 4 | Replace with specific value | User provides number → confirmation → writes |
| Outlier | 5 | At health facility doses only | Noted for HQ; no auto write-back |
| Outlier | 6 | Outreach doses only | Noted for HQ; no auto write-back |
| DTP | 1 | Keep as-is | Closes issue, no data change |
| DTP | 2 | Use DTP1 value for both | Writes Penta3 = Penta1 after confirmation |
| DTP | 3 | Use DTP3 value for both | Writes Penta1 = Penta3 after confirmation |
| DTP | 4 | Replace with specific value | User provides number → confirmation → writes |
| DTP | 5 | Other | Noted, no data change |
| Missing | SUBMIT | Already submitted | Acknowledged, issue closed |
| Missing | 1 | Will submit by [date] | User provides date → confirmation |
| Missing | 2 | Data cannot be recovered | Noted; flagged for HQ imputation |
| Missing | 3 | Facility closed that month | Noted; flagged for HQ zero imputation |
| Missing | 4 | Other | Noted, no data change |

---

## 6. Conversation States

Each inbound reply moves the conversation through one of four states:

| State | What it means | How it ends |
|---|---|---|
| `awaiting_option` | Alert sent; waiting for numbered reply | User sends 1–6 or SUBMIT |
| `awaiting_followup` | Option selected; agent asked for a value | User sends number or date |
| `awaiting_confirmation` | Value ready; agent shows exactly what will change | User replies YES or NO |
| `closed` | Issue resolved or confirmed OK | — |

**NO at confirmation** always re-sends the original options — the user can choose differently.

**Resubmitting data supersedes any open issue.** If the worker re-enters a value in DHIS2 before responding to an alert, the old issue is automatically closed and a fresh one is created. This means the demo can be re-run simply by calling the reset endpoint and re-entering data — no manual DB cleanup needed.

**Multiple issues from one submission are queued, not spammed.** If a single form submission triggers both an outlier and a DTP issue, only the first alert is sent immediately. The second stays as OPEN and is sent once the first conversation closes. This prevents overwhelming the worker and keeps one active conversation per contact at a time.

**Issue log status mirrors conversation state:**
`OPEN` → `NOTIFIED` → `IN PROGRESS` → `CONFIRMING` → `RESOLVED` / `CONFIRMED OK`

Dashboard at `localhost:5001/issues` auto-refreshes every 10 seconds. Each status shows a timestamp in US Eastern time. Open issues have a ↺ Resend button to re-send the alert (useful when the WhatsApp sandbox session expires mid-conversation).

---

## 7. Demo Walkthrough

**Setup:** Two browser tabs side by side — DHIS2 (`localhost:8080`) left, issue log (`localhost:5001/issues`) right. Log in to DHIS2 as `eth_facility_01` / `Ethiopia@2024`.

---

### Demo A — BCG Outlier

1. Navigate: **Data Entry → Addi Arekay Health Center → EPI - Routine vaccine delivery → June 2026**
2. BCG row, `< 1 year` column → type **970** → Tab (field turns green)
3. Watch issue log — within 30s: new row, status **NOTIFIED**
4. WhatsApp alert arrives from Twilio sandbox number
5. Reply **4** → status → **IN PROGRESS**; agent: *"Please reply with the correct value (numbers only, e.g. 97)."*
6. Reply **97** → status → **CONFIRMING**; agent: *"BCG (under 1 year) — Addi Arekay Health Center (Jun 2026) / 970 → 97 / Reply YES or NO"*
7. Reply **YES** → DHIS2 updated; status → **RESOLVED**; agent: *"[DQ-XXXX] Noted. BCG (under 1 year) corrected to 97 in DHIS2. Thank you."*
8. Refresh DHIS2 form — BCG now shows **97** (stored by `agent_service`)

**Show the NO path:** At step 7, reply NO — original 6-option alert is re-sent; user can choose differently.

**Show option 1 instead:** At step 5, reply **1** — agent auto-computes 6-month average (e.g. 99), sends *"970 → 99 (6-month average)"* confirmation. Reply YES to apply without typing a value.

---

### Demo B — DTP Inconsistency

1. Same June 2026 form
2. **DPT-HepB-HIB 1** row, `< 1 year` → type **60** → Tab
3. **DPT-HepB-HIB 3** row, `< 1 year` → type **90** → Tab
4. Alert arrives within 30s showing both fields with full names and the gap percentage
5. Reply **2** → status → **CONFIRMING**; agent: *"DTP3 (under 1 year) — Addi Arekay HC (Jun 2026) / 90 → 60 (use DTP1 value for both)"*
6. Reply **YES** → DTP3 corrected to 60 in DHIS2; status → **RESOLVED**

> DTP3 can never exceed DTP1 — more children cannot complete the series than started it. Flagged because |(90−60)/60| = 50% > 30% threshold.

---

### Demo C — Missing Report

Trigger manually (simulates the daily 8am job):

```bash
curl -s -X POST http://localhost:5001/api/scan \
  -H "Content-Type: application/json" \
  -d '{"period": "202606"}'
```

Alert arrives for each facility without a completed submission. Reply **SUBMIT** (if you've already completed the form in Demo A/B) or **1** followed by a date.

---

### Demo D — Issue Log Dashboard

Open `localhost:5001/issues`. Show:
- All issues from Demos A–C with colour-coded statuses
- Resolution notes column showing exactly what was written to DHIS2
- That the page updates in real time — keep it open during Demos A/B and watch status change as you reply

---

## 8. V0 vs AHEAD Guide: Gap Analysis

| Check | Specified | Implemented | Gap |
|---|---|---|---|
| Outlier — methods | 5 methods; 4+ = strong flag | 2 methods (SD + absolute diff); both must agree | Methods 2–4 deferred to V1 |
| Outlier — SD threshold | > 2 SD (Table 1 operational) | 2.0 SD | Matches exactly |
| Outlier — absolute threshold | > 100 doses | 100 doses | Matches exactly |
| Outlier — baseline contamination | Median AD (method 3) is immune to historical errors | Leave-one-out Z-score is still affected | **Highest-priority V1 fix** — see masking note below |
| DTP thresholds | 30%/100 monthly facility | 30%/100 ✓ | Matches exactly |
| DTP logic | OR | OR ✓ | Matches exactly |
| Missing detection | Cell-level completeness | Dataset registration only | Individual blank cells not caught |
| Region-name consistency | Section 2.1 | Not implemented | Phase 2 batch process |

**On baseline contamination (masking):** If previous errors were never corrected in DHIS2, they pull the historical mean toward themselves, inflating the baseline and making new outliers harder to detect. Example: an uncorrected BCG=200 from 2025 raises the baseline mean so BCG=190 in 2026 appears plausible. V0's leave-one-out only removes the *current* value from its own baseline — it does not clean other periods. The AHEAD guide's Median Absolute Deviation (method 3) uses the median instead of the mean and is completely immune to this — the median cannot be shifted by extreme values. This is the top V1 detection priority.

---

## 9. V1 Roadmap

### P0 — Required before any real deployment

| Item | Notes |
|---|---|
| Production SMS/WhatsApp | Africa's Talking for Ethiopian numbers; or Twilio WhatsApp Business. Code change is `agent/sms.py` only. |
| PostgreSQL | Change connection string in `agent/db.py`. Schema is already compatible. |
| Server deployment | Cloud VM (AWS/Azure/GCP) + systemd service + real domain + SSL. Removes ngrok entirely. |
| Contact registry management | CSV import or minimal admin UI — currently requires editing a Python file. |
| Twilio webhook security | Add signature validation to `POST /webhook/sms`. Currently unauthenticated. |

### P1 — Improves detection quality

| Item | Notes |
|---|---|
| Median Absolute Deviation (method 3) | Immune to baseline contamination. Top priority. Implement in `dhis2_client.get_outliers()`. |
| Full 5-method ensemble | Add MAD (2), Lowess (4). Map method-count to alert urgency: 4+ = immediate, 1–3 = weekly batch. |
| Cell-level missing detection | Check individual blank cells within submitted forms, not just dataset registration. |
| Admin2 rollup | Aggregate facility data to zone level; run DTP consistency with admin2 thresholds. Separate trigger (end of period). |
| Historical data audit | Before deploying on a real country instance: review whether existing DHIS2 data has uncorrected errors that contaminate the baseline. |

### P2 — Polish and integration

| Item | Notes |
|---|---|
| Email notifications | `contacts.email` column already exists. Add email channel (SendGrid/SMTP). |
| Monthly national digest | Implement the `_job_monthly_summary()` stub in `app.py`. |
| Audit trail export | Export `issues` + `conversations` tables into the AHEAD analytics pipeline. |
| Multi-country setup wizard | `config.example.py` already documents all parameters. Automate UID lookup from a target DHIS2 instance. |

---

## 10. Open Questions for George's Team

**Data and thresholds**
1. What is the actual reporting deadline in Ethiopia — is day 10 of the following month accurate?
2. Are the AHEAD Table 1 thresholds (2 SD, 100 doses) right at facility level, or should thresholds be tiered by facility type (health center vs health post vs hospital)?
3. Which antigens should be monitored? V0 covers BCG, Penta1, Penta3, MR1.
4. How clean is the historical DHIS2 data in Ethiopia? Uncorrected errors contaminate the Z-score baseline. A historical audit may be needed before deploying.

**Notification and channel**
5. Is WhatsApp the right channel for Ethiopian health facility workers, or SMS/voice? Does it vary between health centers and health posts?
6. Who holds the phone number at a facility — the in-charge, the data focal point, or whoever physically uses DHIS2?
7. What language — English or Amharic? Are data entry workers comfortable replying in English?
8. Should "Campaign/PIRI" be a response option? It's the most common real-world reason for a spike but is not in the AHEAD guide's dropdown schema.

**Workflow integration**
9. Does AHEAD produce a DQ sheet per country or per admin1 region? The issue log may need to be partitioned by region.
10. How does a DHIS2 correction flow back into the AHEAD Excel and analytics pipeline? Is HQ processing manual or does it pull from DHIS2 programmatically?
11. Does the EPI dataset use DHIS2 data approval? If so, `agent_service` writing directly may bypass the approval workflow.
12. Should the agent auto-close an issue if the facility re-enters correct data in DHIS2 without replying to the alert?

**Production**
13. Is Africa's Talking the right SMS provider? Are there MoH-preferred messaging platforms UNICEF uses for other Ethiopia programs?
14. Who maintains the contact registry? George confirmed DHIS2 doesn't maintain phone numbers — does an existing list exist somewhere?
15. What are the data residency requirements — can the agent database (phone numbers, correction history) be hosted on AWS/Azure, or does it need to be on MoH infrastructure?

---

## Appendix: Key Files

| File | Purpose |
|---|---|
| `agent/dq_engine.py` | All three check functions — read this to understand detection logic |
| `agent/dhis2_client.py` | Every DHIS2 API call — outlier Z-score, write-back, poll |
| `agent/state_machine.py` | Conversation routing, Claude parsing, write-back execution |
| `config.py` | All tunable thresholds — change here without touching code |
| `docs/AHEAD_project_notes.pdf` | UNICEF AHEAD reference guide — source of truth for all thresholds and response options |
| `docs/AHEAD_AI_Tech_Architecture.docx` | Full technical spec — DB schema, API call examples, state machine diagram |
| `docs/AHEAD_AI_UX_Workflow.docx` | Complete message templates, conversation flows, detailed demo script |
