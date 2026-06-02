"""
AHEAD AI Agent — Instance Configuration
========================================
Copy this file to config.py and update values for your DHIS2 instance.

  cp config.example.py config.py

This file contains instance-specific metadata: UIDs, thresholds, and
hierarchy settings. None of these values are secrets — it is safe to
commit config.py to version control.

Secrets (passwords, API keys, tokens) stay in .env, not here.

--- Finding UIDs in a DHIS2 instance ---
Datasets:          GET /api/dataSets?fields=id,name&filter=name:like:EPI
Data elements:     GET /api/dataElements?fields=id,name&filter=name:like:BCG
Category OCs:      GET /api/categoryOptionCombos?fields=id,name&filter=name:like:1+year
Root org unit:     GET /api/organisationUnits?level=1&fields=id,name
"""

# ── DHIS2 instance ────────────────────────────────────────────────────────

# Root org unit: the top-level unit the agent scans for DQ issues.
# For a country deployment this is typically the national root.
ROOT_ORG_UNIT_UID  = 'RFhqluFmvRG'   # Ethiopia (level 1)
ROOT_ORG_UNIT_NAME = 'Ethiopia'

# Level number of facilities in the org unit hierarchy.
# Ethiopia: National(1) → Region(2) → Zone(3) → Woreda(4) → Facility(5)
# A 4-level country would use FACILITY_LEVEL = 4, etc.
FACILITY_LEVEL = 5

# ── Datasets ──────────────────────────────────────────────────────────────

# EPI routine vaccine delivery dataset.
# For a country with an existing DHIS2, use their live dataset UID.
ROUTINE_DATASET_UID = 'vI4ihClxSm4'   # WHO EPI Aggregate Package v1.1.0

# ── Data elements ─────────────────────────────────────────────────────────
# The four AHEAD antigens. UIDs differ per DHIS2 instance — always look
# these up rather than copying from another deployment.
DATA_ELEMENTS = {
    'BCG':    'WSy7zOZx1Wl',   # BCG doses administered
    'Penta1': 'hJJlOnVOkV2',   # DTP-HepB-HIB 1 (first dose)
    'Penta3': 'TWWbtMMWD51',   # DTP-HepB-HIB 3 (third dose)
    'MR1':    'kGrnHR9zV2G',   # MR 1 / MCV1 (measles-rubella first dose)
}

# ── Age disaggregation ────────────────────────────────────────────────────
# Category option combo UIDs for the age bands used in DQ checks.
# These are set by the EPI metadata package; look them up per instance.
CATEGORY_OPTION_COMBOS = {
    'under_1': 'JKuWbG5bWAu',   # < 1 year
    'over_1':  'UIQxmxgioxH',   # >= 1 year
}

# ── Outlier detection ─────────────────────────────────────────────────────
# Operational thresholds from AHEAD reference guide (Table 1).
# A value is flagged if EITHER condition is met.
#
# Note: the full 5-method AHEAD ensemble (SD, MAD, Median AD, Lowess,
# Absolute diff) is Phase 2. MVP uses DHIS2 built-in Z-score + the
# absolute threshold below as a supplementary check.
OUTLIER_Z_THRESHOLD   = 3.0    # Standard deviations from facility mean
OUTLIER_ABS_THRESHOLD = 100    # Raw dose difference from mean (method 5 proxy)

# Minimum months of history a facility must have before outlier detection
# runs. Facilities below this threshold are skipped and logged as
# "insufficient history" rather than generating false positives.
OUTLIER_MIN_HISTORY_MONTHS = 3

# ── DTP1/DTP3 consistency ─────────────────────────────────────────────────
# From AHEAD reference guide. A value is flagged if EITHER rel OR abs
# condition is met (whichever fires first). The prototype operates at
# monthly facility level; admin2 thresholds are here for completeness.
#
# rel: relative difference = (Penta3 - Penta1) / Penta1
# abs: absolute dose gap = Penta3 - Penta1
DTP_THRESHOLDS = {
    'facility_monthly': {'rel': 0.30, 'abs': 100},     # >30% or >100 doses
    'admin2_monthly':   {'rel': 0.20, 'abs': 250},     # >20% or >250 doses
    'admin2_annual':    {'rel': 0.15, 'abs': 1000},    # >15% or >1,000 doses
}

# ── Missing report ────────────────────────────────────────────────────────
# Day of the following month on which the agent begins flagging facilities
# with no complete dataset registration. Set to match the country program's
# reporting deadline. Confirm with the country team before going live.
MISSING_REPORT_START_DAY = 10   # default: day 10 of following month

# ── Cascade timers ────────────────────────────────────────────────────────
RETRY_INTERVAL_HOURS = 24    # Hours between retries at facility level
MAX_RETRIES          = 3     # Retries before escalation (72h total at default)

# Days elapsed at a given cascade level before escalating to the next.
# Facility → Woreda happens after MAX_RETRIES × RETRY_INTERVAL_HOURS.
ESCALATION_DAYS = {
    'woreda':  3,    # Days before escalating from facility to woreda
    'zone':   10,    # Days before escalating from woreda to zone
    'region': 17,    # Days before escalating from zone to region
    # National receives end-of-month digest regardless of escalation state
}

# ── Poll interval ─────────────────────────────────────────────────────────
# Frequency of the lastUpdated check. Controls detection latency.
# This has no impact on API cost — DQ checks only fire when changes are found.
POLL_INTERVAL_SEC = 30
