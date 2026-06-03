# AHEAD AI Agent — DQ Logic Explained

**For:** Internal notes / UNICEF AHEAD team review  
**Prototype:** V0 (June 2026)  
**Code references:** `agent/dq_engine.py`, `agent/dhis2_client.py`, `config.py`

---

## How a check gets triggered

The agent runs a lightweight poll every **30 seconds**:

```
GET /api/dataValueSets?lastUpdated=<last_checked_timestamp>
```

If nothing was submitted since the last check, the response is empty and nothing happens. If new data values exist, the agent extracts the unique `(facility, period)` pairs that changed and passes them as a **scope** to the DQ checks — so checks are always targeted, never a full scan of all facilities.

Missing report checks are the exception: you can't detect an absence with an event trigger, so they run on a **daily cron at 8am EAT**, starting on day 10 of the following month (configurable in `config.py`).

---

## Check 1: Outlier Detection

**Source:** `agent/dq_engine.py` → `check_outliers()`, `agent/dhis2_client.py` → `get_outliers()`  
**AHEAD reference:** Section 2.2

### Step 1 — Fetch historical data

The agent pulls all raw data values for all 12 facilities across the past ~2.5 years:

```
GET /api/dataValueSets
  ?dataSet=vI4ihClxSm4
  &orgUnit=RFhqluFmvRG   (Ethiopia root — gets all children)
  &startDate=<900 days ago>
  &endDate=<last day of current month>
  &children=true
```

Important: `endDate` is set to the **last day of the current month**, not today. DHIS2 excludes monthly periods whose end date falls after `endDate`, so using today's date would drop the current period from the scan window.

### Step 2 — Group into time series

The flat list of values gets grouped into time series:

```
(facility UID, antigen UID, age-band UID)  →  [(period, value), ...]
```

Example: all 28 monthly BCG `<1yr` values for Addi Arekay Health Center become one time series.

A series needs at least **3 data points** before outlier detection runs — below that, statistics aren't meaningful.

### Step 3 — Leave-one-out Z-score

For each value in each time series:

```
other_vals = all other periods in this series, EXCLUDING the candidate period
loo_mean   = mean(other_vals)
loo_std    = standard_deviation(other_vals)
zscore     = |value - loo_mean| / loo_std
```

The **leave-one-out** approach is important: if BCG=970 were included in its own baseline, it would inflate the mean and make the Z-score look smaller. By excluding the candidate, the baseline reflects the true historical pattern.

A value passes this step if `zscore ≥ 2.0` (AHEAD guide Table 1 operational threshold for method 1).

### Step 4 — Scope filter

The 2.5-year window may return old outliers that were already in the historical baseline. These are discarded:

```python
if (facility_uid, period) not in changed_pairs:
    continue  # this wasn't submitted just now — skip
```

Only values from the facilities/periods that just changed proceed to the next step.

### Step 5 — Absolute deviation filter (method 5)

Even if Z-score ≥ 2.0, the value is skipped if the raw dose gap is small:

```python
if |value - loo_mean| < 100 doses:
    continue
```

This is the AHEAD guide's method 5 ("absolute difference from mean > 100 doses"). It prevents false positives at small health posts where natural single-dose swings produce high Z-scores (e.g., BCG mean = 2 doses, value = 3 doses → Z-score ≈ 2.5, but the absolute gap is 1 dose, not a real issue).

**Both methods must fire (AND logic).** A value is flagged only if it passes both the Z-score threshold AND the absolute threshold.

### What gets stored in the database

| Field | Value | Example |
|---|---|---|
| `flagged_value` | The submitted value | 970 |
| `expected_low` | `loo_mean - 2.0 × loo_std` | 79 |
| `expected_high` | `loo_mean + 2.0 × loo_std` | 114 |
| `data_element` | Antigen name | BCG |

### What the SMS shows

```
AHEAD DQ Alert [DQ-XXXX]
Addi Arekay Health Center — Jun 2026
BCG: 970 doses (expected 79–114)
```

---

## Check 2: DTP1/DTP3 Consistency

**Source:** `agent/dq_engine.py` → `check_dtp()`  
**AHEAD reference:** Section 2.4

For each `(facility, period)` pair that just changed, the agent fetches Penta1 and Penta3 values and checks:

```python
rel_diff = |Penta3 - Penta1| / Penta1    # relative gap
abs_diff = |Penta3 - Penta1|             # absolute gap

# Flag if EITHER condition holds (OR logic, per AHEAD guide):
if rel_diff > 0.30 or abs_diff > 100:
    create_issue()
```

**Why OR here:** The AHEAD guide specifies OR for DTP. The relative threshold catches percentage-based inconsistencies regardless of facility size. The absolute threshold catches large hospitals where a 25% gap might still represent 250 doses. Either signal is clinically implausible — more children cannot complete the DTP series than started it.

**Why AND for outlier but OR for DTP:** Outlier detection uses AND to control noise at small facilities where Z-scores are high by nature. DTP inconsistency is a structural logical error (DTP3 > DTP1 is biologically impossible) — even a small relative gap is worth flagging, so OR is correct.

### Thresholds (from AHEAD guide, all in `config.py`)

| Level | Relative threshold | Absolute threshold |
|---|---|---|
| Monthly facility (current scope) | > 30% | > 100 doses |
| Monthly admin2 | > 20% | > 250 doses |
| Annual admin2 | > 15% | > 1,000 doses |

### What gets stored

| Field | Value |
|---|---|
| `flagged_value` | Penta3 value (the implausibly high one) |
| `expected_low` | Penta1 value (stored here for SMS display) |
| `expected_high` | Penta1 × 1.30 (maximum acceptable Penta3) |

---

## Check 3: Missing Reports

**Source:** `agent/dq_engine.py` → `check_missing_reports()`  
**AHEAD reference:** Section 2.3

```python
submitted  = GET /api/completeDataSetRegistrations?period=202606&...
             → set of facility UIDs that clicked "Complete" in DHIS2

facilities = GET /api/organisationUnits?level=5&...
             → all 12 facilities

for each facility not in submitted:
    create_issue(type='missing')
```

**When it runs:** Daily at 8am EAT, but only if `today.day ≥ MISSING_REPORT_START_DAY` (default: 10). This matches the AHEAD guide: "the first step is always recovery, not imputation" — the agent doesn't start flagging until the deadline has passed, giving facilities time to submit normally.

**Limitation:** This checks whether the dataset was marked "Complete" — it does not check whether individual cells within a submitted form are blank. A facility that submits a form with some vaccines missing will not be flagged by this check.

---

## Summary: Implementation vs AHEAD Guide

| DQ check | AHEAD guide specifies | V0 implements | Gap |
|---|---|---|---|
| **Outlier — methods** | 5 methods (SD, MAD, Median AD, Lowess, Absolute diff); flag if 4+ agree | 2 methods (SD + Absolute diff); both must agree | Methods 2–4 deferred to V1 |
| **Outlier — SD threshold** | > 2 SD (operational Table 1) | 2.0 SD (`OUTLIER_Z_THRESHOLD` in config.py) | Matches exactly |
| **Outlier — absolute threshold** | > 100 doses | 100 doses (`OUTLIER_ABS_THRESHOLD` in config.py) | Matches exactly |
| **Outlier — ensemble logic** | 4+ of 5 methods = strong flag | Both of 2 methods = flag (conservative equivalent) | Reasonable proxy; misses borderline cases that 3/5 methods would catch |
| **DTP thresholds** | 30%/100 monthly facility | 30%/100 ✓ | Matches exactly |
| **DTP logic** | OR | OR ✓ | Matches exactly |
| **Missing — detection** | Completeness = actual/expected × 100 | Complete registration check | Individual blank cells within a submitted form are not caught |
| **Region-name consistency** | Flag if record count < expected | Not implemented | Phase 2 |

---

## Where to find the code

| File | What it contains |
|---|---|
| [`agent/dq_engine.py`](../agent/dq_engine.py) | All three check functions + entry points |
| [`agent/dhis2_client.py`](../agent/dhis2_client.py) | `get_outliers()` — raw Z-score computation; `get_data_values()` — DTP fetch; `get_complete_registrations()` — missing check |
| [`config.py`](../config.py) | All tunable thresholds (`OUTLIER_Z_THRESHOLD`, `OUTLIER_ABS_THRESHOLD`, `DTP_THRESHOLDS`, `MISSING_REPORT_START_DAY`) |
| [`docs/AHEAD_project_notes.pdf`](AHEAD_project_notes.pdf) | Original AHEAD reference guide — the source of truth for all thresholds and response options |
