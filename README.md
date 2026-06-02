# AHEAD AI Agent — Prototype

**Project:** UNICEF AHEAD × Gates Foundation AI Fellows
**Scope:** AI agent for immunization data quality monitoring in Ethiopia
**Status:** Infrastructure and documentation complete; agent implementation in progress

The agent automates the current manual AHEAD DQ loop — replacing the email + Excel cascade with real-time SMS notifications, structured response options, and automatic corrections written back to DHIS2.

---

## Project structure

```
dhis2-prototype/
├── docker-compose.yml        DHIS2 + PostgreSQL containers
├── dhis.conf.example         DHIS2 database config template
├── .env.example              Secrets template (passwords, API keys)
├── config.example.py         Agent instance config template (DHIS2 UIDs, thresholds)
├── requirements.txt          Python dependencies (python-docx for doc generators)
│
├── dhis2/                    DHIS2 sandbox setup scripts
│   ├── build_ethiopia.py     Phase 2 — builds org unit hierarchy
│   ├── assign_datasets.py    Phase 3 — assigns EPI datasets to facilities
│   ├── build_users.py        Phase 4 — creates role-based user accounts
│   ├── inject_data.py        Phase 5 — loads 28 months of synthetic EPI data
│   ├── IMM_AGG_COMPLETE_1.1.0_DHIS2.40_patched.json   EPI metadata package
│   └── eth_admin_boundaries.xlsx                       Reference data
│
├── docs/                     All documentation
│   ├── dhis2_setup_guide.md        Full step-by-step DHIS2 setup guide
│   ├── AHEAD_AI_Tech_Architecture.docx   Technical implementation spec
│   ├── AHEAD_AI_UX_Workflow.docx         UX, message templates, demo script
│   ├── AHEAD_AI_MVP_Architecture.docx    High-level proposal overview
│   ├── AHEAD_project_notes.pdf           UNICEF AHEAD reference guide
│   ├── generate_tech_doc.py    Regenerates Tech Architecture docx
│   ├── generate_ux_doc.py      Regenerates UX Workflow docx
│   └── generate_doc.py         Regenerates MVP Architecture docx
│
└── agent/                    AI agent code (to be implemented)
```

---

## Prerequisites

- Docker Desktop (running)
- Python 3.x (standard library only for setup scripts; `python-docx` for doc generators)
- ~4 GB disk space

---

## Setup

### 1. Copy config files and fill in values

```bash
cp .env.example .env
cp dhis.conf.example dhis.conf
cp config.example.py config.py
```

- `.env` — set `POSTGRES_PASSWORD` and `DHIS2_USER_PASSWORD`
- `dhis.conf` — set `connection.password` to match `POSTGRES_PASSWORD`
- `config.py` — Ethiopia values are pre-filled; only update if deploying to a different DHIS2 instance

### 2. Start DHIS2

```bash
docker compose up -d
```

Wait ~90 seconds, then confirm:

```bash
curl -s -o /dev/null -w "%{http_code}" -u admin:district http://localhost:8080/api/system/info
# → 200
```

### 3. Import the EPI metadata package (one-time)

```bash
curl -s -u admin:district \
  -X POST "http://localhost:8080/api/metadata?importMode=COMMIT&mergeMode=REPLACE&skipSharing=false" \
  -H "Content-Type: application/json" \
  -d @dhis2/IMM_AGG_COMPLETE_1.1.0_DHIS2.40_patched.json \
  | python3 -c "import sys,json; r=json.load(sys.stdin); print(r.get('status'), r.get('stats',{}))"
```

Then unlock the EPI datasets:

```bash
docker compose exec db psql -U dhis -d dhis2 -c \
  "UPDATE dataset SET publicaccess='rwrw----' WHERE uid IN ('vI4ihClxSm4','jqSaKxtj8IA');"
```

### 4. Build the org unit hierarchy and users

Run all scripts from the **project root**:

```bash
python3 dhis2/build_ethiopia.py
```

Grant admin scope over the new hierarchy (see [docs/dhis2_setup_guide.md](docs/dhis2_setup_guide.md) — Phase 2 SQL fix), then:

```bash
python3 dhis2/assign_datasets.py
python3 dhis2/build_users.py
python3 dhis2/inject_data.py
```

### 5. Verify

Open [http://localhost:8080](http://localhost:8080) and log in with one of the accounts below.

---

## Demo accounts

| Username | Password | Scope |
|---|---|---|
| `admin` | `DHIS2_ADMIN_PASS` (from `.env`) | Full access |
| `eth_facility_01` | `DHIS2_USER_PASSWORD` (from `.env`) | Addi Arekay Health Center only |
| `eth_woreda_01` | `DHIS2_USER_PASSWORD` | Addi Arekay Woreda |
| `eth_zone_01` | `DHIS2_USER_PASSWORD` | North Gondar Zone (view only) |
| `eth_regional_01` | `DHIS2_USER_PASSWORD` | Amhara Region (view only) |
| `eth_national_01` | `DHIS2_USER_PASSWORD` | Ethiopia national (view only) |

---

## Running the demo

Log in as `eth_facility_01`. All demos use **Addi Arekay Health Center** and **June 2026** data (no data loaded for that period yet — you enter it live).

See **[docs/AHEAD_AI_UX_Workflow.docx](docs/AHEAD_AI_UX_Workflow.docx)** Section 10 for the step-by-step demo script with exact navigation paths, values to type, and expected SMS conversation for each scenario.

---

## Regenerating documentation

All `.docx` files are generated from Python scripts. To regenerate after edits:

```bash
pip install python-docx   # one-time

python3 docs/generate_tech_doc.py   # → docs/AHEAD_AI_Tech_Architecture.docx
python3 docs/generate_ux_doc.py     # → docs/AHEAD_AI_UX_Workflow.docx
python3 docs/generate_doc.py        # → docs/AHEAD_AI_MVP_Architecture.docx
```

Edit the generator scripts to update the documents; never edit the `.docx` files directly.

---

## Resetting the DHIS2 instance

To wipe everything and start over:

```bash
docker compose down
docker volume ls | grep -E 'db-data|dhis2-home' | awk '{print $2}' | xargs docker volume rm
docker compose up -d
```

Then re-run phases 1d through 5 in order (see [docs/dhis2_setup_guide.md](docs/dhis2_setup_guide.md)).

---

## Key documents

| Document | What it covers |
|---|---|
| [docs/dhis2_setup_guide.md](docs/dhis2_setup_guide.md) | Full reproducible setup walkthrough for the DHIS2 sandbox |
| [docs/AHEAD_AI_Tech_Architecture.docx](docs/AHEAD_AI_Tech_Architecture.docx) | Technical implementation spec for the AI agent |
| [docs/AHEAD_AI_UX_Workflow.docx](docs/AHEAD_AI_UX_Workflow.docx) | SMS message templates, conversation flows, demo script |
| [docs/AHEAD_project_notes.pdf](docs/AHEAD_project_notes.pdf) | UNICEF AHEAD reference guide (DQ methodology source) |
| [config.example.py](config.example.py) | Instance config template — update UIDs when deploying to a new country |
