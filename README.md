# AHEAD AI Agent — Prototype

**Project:** UNICEF AHEAD × Gates Foundation
**Scope:** AI agent for immunization data quality monitoring in Ethiopia
**Status:** Agent fully implemented and tested end-to-end

The agent automates the current manual AHEAD DQ loop — replacing the email + Excel cascade
with real-time WhatsApp/SMS notifications, structured response options (matching the AHEAD Excel
dropdowns), automatic corrections written back to DHIS2, and a live issue log dashboard.

---

## Project structure

```
dhis2-prototype/
├── docker-compose.yml          DHIS2 + PostgreSQL containers
├── dhis.conf.example           DHIS2 database config template
├── .env.example                Secrets template (passwords, API keys)
├── config.example.py           Agent instance config (DHIS2 UIDs, thresholds)
├── requirements.txt            Python dependencies
│
├── dhis2/                      DHIS2 sandbox setup scripts
│   ├── build_ethiopia.py       Phase 2 — org unit hierarchy (5 levels, 12 facilities)
│   ├── assign_datasets.py      Phase 3 — assigns EPI datasets to facilities
│   ├── build_users.py          Phase 4 — creates role-based user accounts + agent_service
│   ├── inject_data.py          Phase 5 — loads 28 months of clean synthetic EPI data
│   ├── IMM_AGG_COMPLETE_1.1.0_DHIS2.40_patched.json   WHO EPI metadata package
│   └── eth_admin_boundaries.xlsx                       Reference data
│
├── docs/                       All documentation
│   ├── dhis2_setup_guide.md        Full step-by-step DHIS2 setup guide
│   ├── AHEAD_AI_Tech_Architecture.docx   Technical implementation spec
│   ├── AHEAD_AI_UX_Workflow.docx         UX, message templates, conversation flows, demo script
│   ├── AHEAD_AI_MVP_Architecture.docx    High-level proposal overview
│   ├── AHEAD_project_notes.pdf           UNICEF AHEAD reference guide (DQ methodology source)
│   ├── generate_tech_doc.py        Regenerates Tech Architecture docx
│   ├── generate_ux_doc.py          Regenerates UX Workflow docx
│   └── generate_doc.py             Regenerates MVP Architecture docx
│
└── agent/                      AI agent (fully implemented)
    ├── app.py                  Entry point — Flask + APScheduler
    ├── db.py                   SQLite schema (contacts, issues, conversations, hierarchy)
    ├── dhis2_client.py         DHIS2 REST API wrapper (poll, outlier, DTP, write-back)
    ├── dq_engine.py            DQ logic — outlier / DTP / missing checks
    ├── sms.py                  Twilio/WhatsApp wrapper + AHEAD-aligned message templates
    ├── state_machine.py        Conversation state + Claude API option parsing
    └── seed_contacts.py        Populates the notification contact registry
```

---

## Prerequisites

- Docker Desktop (running)
- Python 3.x — install packages: `pip3 install -r requirements.txt`
- ~4 GB disk space
- Claude API key (option parsing) — [console.anthropic.com](https://console.anthropic.com)
- Twilio account (WhatsApp/SMS) — [twilio.com](https://twilio.com)
- ngrok account (webhook tunnel) — [ngrok.com](https://ngrok.com)

---

## One-time DHIS2 setup

> Only needed once. Skip to **Running the agent** if DHIS2 is already configured.

### 1. Copy config files

```bash
cp .env.example .env
cp dhis.conf.example dhis.conf
cp config.example.py config.py
```

Fill in `.env`: set `POSTGRES_PASSWORD`, `DHIS2_USER_PASSWORD`, and all agent credentials (see `.env.example` for the full list).
Fill in `dhis.conf`: set `connection.password` to match `POSTGRES_PASSWORD`.

### 2. Start DHIS2

```bash
docker compose up -d
```

Wait ~90 seconds, then confirm:

```bash
curl -s -o /dev/null -w "%{http_code}" -u admin:district http://localhost:8080/api/system/info
# → 200
```

### 3. Import the EPI metadata package

```bash
curl -s -u admin:district \
  -X POST "http://localhost:8080/api/metadata?importMode=COMMIT&mergeMode=REPLACE&skipSharing=false" \
  -H "Content-Type: application/json" \
  -d @dhis2/IMM_AGG_COMPLETE_1.1.0_DHIS2.40_patched.json \
  | python3 -c "import sys,json; r=json.load(sys.stdin); print(r.get('status'), r.get('stats',{}))"
```

Unlock the EPI datasets:

```bash
docker compose exec db psql -U dhis -d dhis2 -c \
  "UPDATE dataset SET publicaccess='rwrw----' WHERE uid IN ('vI4ihClxSm4','jqSaKxtj8IA');"
```

### 4. Build the org unit hierarchy and users

```bash
python3 dhis2/build_ethiopia.py
```

Grant admin scope over the new hierarchy (see [docs/dhis2_setup_guide.md](docs/dhis2_setup_guide.md) — Phase 2 SQL fix), then:

```bash
python3 dhis2/assign_datasets.py
python3 dhis2/build_users.py
python3 dhis2/inject_data.py
```

### 5. Demo accounts

| Username | Password | Scope |
|---|---|---|
| `admin` | from `.env` (`DHIS2_ADMIN_PASS`) | Full access |
| `eth_facility_01` | from `.env` (`DHIS2_USER_PASSWORD`) | Addi Arekay Health Center only |
| `eth_woreda_01` | same | Addi Arekay Woreda |
| `eth_zone_01` | same | North Gondar Zone (view only) |
| `eth_regional_01` | same | Amhara Region (view only) |
| `eth_national_01` | same | Ethiopia national (view only) |
| `agent_service` | from `.env` (`AGENT_PASS`) | System account — do not use for data entry |

---

## Running the agent

### 1. Configure WhatsApp sandbox (demo mode)

The demo uses Twilio's **WhatsApp sandbox** to bypass US carrier SMS registration requirements. This is a one-time setup per device receiving alerts.

**On the phone that will receive alerts** (e.g., the demo presenter's phone):

1. Open WhatsApp
2. Send a message to **+1 415 523 8886**
3. The message body should be your sandbox keyword — find it at **[twilio.com/console → Messaging → Try it out → Send a WhatsApp message](https://console.twilio.com)**
4. You will receive an auto-reply confirming you are connected

> For production: set `TWILIO_WHATSAPP=false` in `.env` and use standard SMS with a registered A2P 10DLC number.

### 2. Seed the contact registry

Open `agent/seed_contacts.py` and update the `eth_facility_01` phone number in `build_contacts()` to the real phone number that will receive alerts. Then run:

```bash
python3 agent/seed_contacts.py --clear
```

### 3. Start the agent

```bash
python3 agent/app.py
```

On startup the agent prints:

```
[APP] org_unit_hierarchy seeded from ethiopia_uid_map.json
[APP] DHIS2 reachable — agent_service authenticated
[APP] scheduler started — poll every 30s
[NGROK] public URL: https://xxxx.ngrok-free.app
[NGROK] *** set Twilio webhook → https://xxxx.ngrok-free.app/webhook/sms ***
```

### 4. Set the Twilio WhatsApp webhook

1. Copy the `https://xxxx.ngrok-free.app/webhook/sms` URL from the startup output
2. Go to **[twilio.com/console → Messaging → Try it out → Send a WhatsApp message](https://console.twilio.com)**
3. Paste the URL into **"When a message comes in"** and save

> The ngrok URL changes every time the agent restarts. Update the webhook URL each session.

### 5. Verify

```bash
curl -s http://localhost:5001/api/health
# → {"dhis2": true, "open_issues": 0}
```

Open the issue log at [http://localhost:5001/issues](http://localhost:5001/issues). It should show an empty table — ready for the demo.

---

## Demo — step by step

> Keep two browser tabs open side by side: DHIS2 on the left, issue log (`localhost:5001/issues`) on the right. The issue log auto-refreshes every 10 seconds so you can watch status change in real time as you respond to WhatsApp messages.

### Before the demo

**Warm up the WhatsApp sandbox** — open WhatsApp on your phone and send any message (e.g. "hi") to **+1 415 523 8886**. The sandbox session expires after 24 hours of inactivity; sending a message right before the demo resets the clock and ensures all 4 turns of the conversation are delivered reliably.

Reset the agent database so the issue log starts empty:

```bash
# Stop the agent first (Ctrl+C), then:
python3 -c "
import sys; sys.path.insert(0,'agent'); sys.path.insert(0,'.')
from db import get_conn
with get_conn() as conn:
    conn.execute('DELETE FROM conversations')
    conn.execute('DELETE FROM issues')
    conn.execute('DELETE FROM poll_state')
print('Reset complete')
"
# Restart the agent
python3 agent/app.py
```

---

### Demo A — Outlier detection: BCG data entry error

**What this shows:** A facility worker enters an obviously wrong value. The agent detects it within 30 seconds, sends a WhatsApp alert, walks the worker through selecting a correction option, asks for confirmation, and writes the corrected value back to DHIS2 automatically.

**Step 1 — Open the data entry form**

1. Go to [http://localhost:8080](http://localhost:8080)
2. Log in as `eth_facility_01` / `Ethiopia@2024`
3. Navigate to: **Data Entry** (top menu) → Organisation Unit: **Addi Arekay Health Center** → Data Set: **EPI - Routine vaccine delivery** → Period: **June 2026**

**Step 2 — Enter the bad value**

In the **Vaccinations - children** table, find the **BCG** row. In the **< 1 year** column, type:

```
970
```

Press Tab or click away. The field turns green — the value is saved to DHIS2.

> Expected baseline for this facility is ~90–110 doses/month. 970 is a 10× outlier.

**Step 3 — Watch the issue log**

Switch to [http://localhost:5001/issues](http://localhost:5001/issues). Within 30 seconds, a new row appears:

| Ref ID | Type | Facility | Period | Element | Value | Expected | Status |
|---|---|---|---|---|---|---|---|
| DQ-XXXX | OUTLIER | Addi Arekay Health Center | 202606 | BCG | 970 | 79–114 | NOTIFIED |

**Step 4 — Receive the WhatsApp alert**

Your phone receives a WhatsApp message from the Twilio sandbox number:

```
AHEAD DQ Alert [DQ-XXXX]
Addi Arekay Health Center — Jun 2026
BCG: 970 doses (expected 79–114)

Reply with option number:
1. Replace with 6-month average
2. Keep as-is (no action)
3. Set to zero
4. Replace with specific value
5. At health facility doses only
6. Outreach doses only
```

**Step 5 — Select an option**

Reply **`4`** (replace with specific value — you know the correct value was 97).

The issue log status updates to **IN PROGRESS**.

You receive:

```
Please reply with the correct value (numbers only, e.g. 97).
```

**Step 6 — Provide the correct value**

Reply **`97`**

The issue log status updates to **CONFIRMING**.

You receive:

```
[DQ-XXXX] Confirm change:
BCG <1yr — Addi Arekay Health Center (Jun 2026)
970 → 97

Reply YES to update DHIS2 or NO to re-enter.
```

**Step 7 — Confirm**

Reply **`YES`**

The agent writes `97` to DHIS2. You receive:

```
[DQ-XXXX] Noted. Value corrected to 97 in DHIS2. Thank you.
```

The issue log status updates to **RESOLVED**.

**Step 8 — Verify in DHIS2**

Refresh the DHIS2 data entry form. The BCG < 1 year field now shows **97** — updated by `agent_service`.

---

### Demo B — DTP inconsistency: DTP3 > DTP1

**What this shows:** The agent catches a biologically implausible value combination — more children received a third dose than a first dose, which is epidemiologically impossible. The agent automatically computes the correction and writes it back to DHIS2 with one confirmation.

**Step 1 — Open the data entry form**

Same form as Demo A, or start fresh after resetting:

**Data Entry** → **Addi Arekay Health Center** → **EPI - Routine vaccine delivery** → **June 2026**

**Step 2 — Enter the inconsistent values**

In the **Vaccinations - children** table:

- **DPT-HepB-HIB 1** row, `< 1 year` column → type **`60`**, press Tab
- **DPT-HepB-HIB 3** row, `< 1 year` column → type **`90`**, press Tab

Both fields turn green (saved).

> **Why this is a DQ issue:** Every child who receives dose 3 must have received doses 1 and 2 first — DTP3 can never exceed DTP1. DTP3 = 90 > DTP1 = 60 means 30 children appear to have completed the series without ever starting it.
>
> **The threshold:** relative gap > 30% OR absolute gap > 100 doses. Here |(90 − 60) / 60| = 50% — flagged on the relative condition.

**Step 3 — Watch the issue log**

At [http://localhost:5001/issues](http://localhost:5001/issues), within 30 seconds a new row appears with status **NOTIFIED**.

**Step 4 — Receive the WhatsApp alert**

```
AHEAD DQ Alert [DQ-YYYY]
Addi Arekay Health Center — Jun 2026
DTP1=60, DTP3=90 (DTP3 > DTP1, gap: 50%)

Reply with option number:
1. Keep as-is (no action)
2. Use DTP1 value for both
3. Use DTP3 value for both
4. Replace with specific value
5. Other reason
```

**Step 5 — Select option 2**

Reply **`2`** (set both DTP1 and DTP3 to the DTP1 value — DTP1 is the more reliable count since it's the entry dose).

The issue log updates to **CONFIRMING**. You receive:

```
[DQ-YYYY] Confirm: Set DTP3 to match DTP1 (60)
Addi Arekay Health Center (Jun 2026)

Reply YES to update DHIS2 or NO to choose again.
```

**Step 6 — Confirm**

Reply **`YES`**

The agent writes Penta3 = 60 to DHIS2. You receive:

```
[DQ-YYYY] Noted. DTP3 set to match DTP1 (60) in DHIS2. Thank you.
```

The issue log updates to **RESOLVED**. Refresh the DHIS2 form — DPT-HepB-HIB 3 now shows **60**.

---

### Demo C — Missing report

**What this shows:** The agent identifies facilities that haven't submitted their monthly report and prompts recovery.

**Trigger the check manually** (simulates the daily 8am job):

```bash
curl -s -X POST http://localhost:5001/api/scan \
  -H "Content-Type: application/json" \
  -d '{"period": "202606"}'
```

This creates a missing-report issue for every facility that hasn't completed the June 2026 dataset. The facility contact receives:

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

Reply **`SUBMIT`** (if you've already completed the form) or **`1`** followed by a date to schedule submission.

---

### Demo D — Issue log dashboard

Open [http://localhost:5001/issues](http://localhost:5001/issues) to show the audience:

- All detected issues listed with ref IDs, facility, period, element, and flagged value
- Live status column — colour-coded and updating in real time:
  - **OPEN** (orange) — issue created, alert sent
  - **NOTIFIED** (amber) — alert delivered, awaiting reply
  - **IN PROGRESS** (blue) — first reply received
  - **CONFIRMING** (purple) — value provided, waiting for YES/NO
  - **RESOLVED** (green) — correction applied
  - **CONFIRMED OK** (grey) — worker confirmed the value is correct
- Resolution notes column — shows exactly what the agent wrote back to DHIS2

---

### Demo tips

- **Run Demos A and B together** — enter BCG=970 AND the DTP values in the same form submission. Two alerts fire within seconds of each other, showing the agent handling multiple concurrent issues.
- **Show "NO" rejection** — at the confirmation step, reply `NO` instead of `YES`. The original options are re-sent. This shows the system never writes to DHIS2 without explicit confirmation.
- **Show the option 1 flow** — after entering BCG=970, reply `1` instead of `4`. The agent auto-computes the 6-month historical average, shows it in the confirmation prompt, and writes it after YES. No manual value needed.
- **Reset between runs** — use the reset script above; then also correct BCG back to 970 manually in DHIS2 (or re-enter it in the form) so the outlier is detectable again.

---

## DQ methodology

The agent implements three of the four AHEAD DQ checks (section 2 of `docs/AHEAD_project_notes.pdf`):

| Check | AHEAD section | What's flagged | Thresholds |
|---|---|---|---|
| Statistical outlier | 2.2 | Value deviates from facility historical baseline | Z-score > 2.0 SD (method 1) OR absolute diff > 100 doses (method 5) |
| DTP1/DTP3 consistency | 2.4 | Penta3 > Penta1 for same facility-period | Relative gap > 30% OR absolute gap > 100 doses (monthly facility) |
| Missing report | 2.3 | No completed dataset registration by day 10 of following month | 100% completeness required |

**Phase 2 additions:** Region-name consistency (section 2.1); full 5-method outlier ensemble (SD, MAD, Median AD, Lowess, Absolute diff); admin2-level DTP thresholds.

---

## Resetting the DHIS2 instance

To wipe everything and start over from scratch:

```bash
docker compose down
docker volume ls | grep -E 'db-data|dhis2-home' | awk '{print $2}' | xargs docker volume rm
docker compose up -d
```

Then re-run the one-time DHIS2 setup steps above.

---

## Regenerating documentation

All `.docx` files are generated from Python scripts — never edit the `.docx` files directly.

```bash
pip install python-docx   # one-time

python3 docs/generate_tech_doc.py   # → docs/AHEAD_AI_Tech_Architecture.docx
python3 docs/generate_ux_doc.py     # → docs/AHEAD_AI_UX_Workflow.docx
python3 docs/generate_doc.py        # → docs/AHEAD_AI_MVP_Architecture.docx
```

---

## Key documents

| Document | What it covers |
|---|---|
| [docs/dhis2_setup_guide.md](docs/dhis2_setup_guide.md) | Full reproducible DHIS2 sandbox setup walkthrough |
| [docs/AHEAD_AI_Tech_Architecture.docx](docs/AHEAD_AI_Tech_Architecture.docx) | Technical implementation spec — architecture, APIs, state machine |
| [docs/AHEAD_AI_UX_Workflow.docx](docs/AHEAD_AI_UX_Workflow.docx) | Message templates, conversation flows, full demo script |
| [docs/AHEAD_project_notes.pdf](docs/AHEAD_project_notes.pdf) | UNICEF AHEAD reference guide — DQ methodology and response option schema |
| [config.example.py](config.example.py) | Instance config template — update UIDs and thresholds for a different country |
