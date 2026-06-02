#!/usr/bin/env python3
"""
DQ engine: runs outlier, DTP consistency, and missing report checks against DHIS2.

Checks:
  check_outliers(changed_pairs)   — DHIS2 Z-score API + absolute-deviation filter
  check_dtp(changed_pairs)        — Penta1 vs Penta3 consistency
  check_missing_reports(period)   — facilities with no complete dataset registration

Each function creates new issue rows in the DB and returns their ref_ids.
Existing open issues for the same (facility, period, element) are not duplicated.
"""

import sys, pathlib
_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from datetime import date, timedelta
import config as cfg
import dhis2_client as dc
from db import get_conn, gen_ref_id

# Reverse map: UID → antigen name (e.g. 'WSy7zOZx1Wl' → 'BCG')
_DE_NAME = {v: k for k, v in cfg.DATA_ELEMENTS.items()}


def _open_issue_exists(conn, facility_uid, period, data_element, issue_type):
    return conn.execute(
        "SELECT 1 FROM issues "
        "WHERE facility_uid=? AND period=? AND data_element IS ? AND issue_type=? "
        "AND status NOT IN ('resolved', 'ignored')",
        (facility_uid, period, data_element, issue_type)
    ).fetchone() is not None


def _create_issue(conn, issue_type, facility_uid, facility_name, period,
                  data_element=None, flagged_value=None, expected_low=None, expected_high=None):
    ref_id = gen_ref_id(conn)
    conn.execute("""
        INSERT INTO issues
          (ref_id, issue_type, facility_uid, facility_name, period,
           data_element, flagged_value, expected_low, expected_high)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (ref_id, issue_type, facility_uid, facility_name, period,
          data_element, flagged_value, expected_low, expected_high))
    return ref_id


# ── Outlier check ─────────────────────────────────────────────────────────────

def check_outliers(changed_pairs=None):
    """
    Call DHIS2 built-in Z-score outlier detection.

    changed_pairs: set of (org_unit_uid, period_str) to filter on.
                   If None, all outliers in the scan window are evaluated.

    A value is flagged only if BOTH conditions hold:
      1. Z-score exceeds OUTLIER_Z_THRESHOLD (DHIS2 filters this for us)
      2. Absolute deviation from mean exceeds OUTLIER_ABS_THRESHOLD (method 5 proxy)

    Returns list of newly created ref_ids.
    """
    start = (date.today() - timedelta(days=900)).strftime('%Y-%m-%d')  # ~2.5 years
    end   = date.today().strftime('%Y-%m-%d')

    try:
        outliers = dc.get_outliers(
            cfg.ROUTINE_DATASET_UID, cfg.ROOT_ORG_UNIT_UID,
            start, end, cfg.OUTLIER_Z_THRESHOLD
        )
    except Exception as e:
        print(f'[DQ] outlier API error: {e}')
        return []

    new_refs = []
    with get_conn() as conn:
        for o in outliers:
            ou_uid  = o.get('ou', '')
            period  = o.get('pe', '')
            de_uid  = o.get('de', '')
            value   = o.get('value')
            mean    = o.get('mean')
            std_dev = o.get('stdDev', 0)

            # Filter to recently changed pairs when this is a triggered (not manual) scan
            if changed_pairs and (ou_uid, period) not in changed_pairs:
                continue

            de_name = _DE_NAME.get(de_uid)
            if not de_name:
                continue  # not a tracked antigen

            # Apply absolute-deviation filter to reduce false positives on small baselines
            if value is not None and mean is not None:
                if abs(value - mean) < cfg.OUTLIER_ABS_THRESHOLD:
                    continue

            if _open_issue_exists(conn, ou_uid, period, de_name, 'outlier'):
                continue

            expected_low  = round(mean - cfg.OUTLIER_Z_THRESHOLD * std_dev, 1) if mean and std_dev else None
            expected_high = round(mean + cfg.OUTLIER_Z_THRESHOLD * std_dev, 1) if mean and std_dev else None

            ref = _create_issue(
                conn, 'outlier', ou_uid, o.get('ouName', ou_uid), period,
                de_name, value, expected_low, expected_high
            )
            new_refs.append(ref)
            print(f'[DQ] outlier: {ref}  {o.get("ouName")} {period} {de_name}={value} (mean={mean:.1f})')

    return new_refs


# ── DTP consistency check ─────────────────────────────────────────────────────

def check_dtp(changed_pairs=None):
    """
    Check Penta1/Penta3 (DTP1/DTP3) consistency for each (facility, period) pair.

    Flags if EITHER condition holds (per AHEAD guide facility-monthly thresholds):
      rel: |(Penta3 - Penta1) / Penta1| > 30%
      abs: |Penta3 - Penta1| > 100 doses

    Returns list of newly created ref_ids.
    """
    if not changed_pairs:
        return []

    p1_uid = cfg.DATA_ELEMENTS.get('Penta1')
    p3_uid = cfg.DATA_ELEMENTS.get('Penta3')
    coc    = cfg.CATEGORY_OPTION_COMBOS.get('under_1')
    thresh = cfg.DTP_THRESHOLDS.get('facility_monthly', {'rel': 0.30, 'abs': 100})

    if not (p1_uid and p3_uid and coc):
        return []

    new_refs = []
    with get_conn() as conn:
        for (ou_uid, period) in changed_pairs:
            try:
                values = dc.get_data_values(cfg.ROUTINE_DATASET_UID, ou_uid, period)
            except Exception as e:
                print(f'[DQ] DTP fetch error {ou_uid} {period}: {e}')
                continue

            p1 = values.get((p1_uid, coc))
            p3 = values.get((p3_uid, coc))

            if p1 is None or p3 is None or p1 == 0:
                continue  # can't compute ratio without both values

            rel_diff = abs((p3 - p1) / p1)
            abs_diff = abs(p3 - p1)

            if rel_diff <= thresh['rel'] and abs_diff <= thresh['abs']:
                continue

            row = conn.execute(
                'SELECT facility_name FROM org_unit_hierarchy WHERE facility_uid=?',
                (ou_uid,)
            ).fetchone()
            fac_name = row['facility_name'] if row else ou_uid

            if _open_issue_exists(conn, ou_uid, period, 'DTP', 'dtp'):
                continue

            ref = _create_issue(
                conn, 'dtp', ou_uid, fac_name, period,
                data_element='DTP',
                flagged_value=p3,
                expected_low=p1,   # store Penta1 here for display in SMS template
                expected_high=round(p1 * (1 + thresh['rel']), 1)
            )
            new_refs.append(ref)
            print(f'[DQ] DTP: {ref}  {fac_name} {period} Penta1={p1} Penta3={p3}')

    return new_refs


# ── Missing report check ──────────────────────────────────────────────────────

def check_missing_reports(period):
    """
    Identify facilities that have not submitted a complete dataset registration
    for period (YYYYMM). Creates one 'missing' issue per absent facility.

    Returns list of newly created ref_ids.
    """
    try:
        submitted  = dc.get_complete_registrations(
            cfg.ROUTINE_DATASET_UID, cfg.ROOT_ORG_UNIT_UID, period
        )
        facilities = dc.get_facilities_in_scope(cfg.ROOT_ORG_UNIT_UID, cfg.FACILITY_LEVEL)
    except Exception as e:
        print(f'[DQ] missing report check error: {e}')
        return []

    new_refs = []
    with get_conn() as conn:
        for fac in facilities:
            if fac['uid'] in submitted:
                continue
            if _open_issue_exists(conn, fac['uid'], period, None, 'missing'):
                continue

            ref = _create_issue(
                conn, 'missing', fac['uid'], fac['name'], period
            )
            new_refs.append(ref)
            print(f'[DQ] missing: {ref}  {fac["name"]} {period}')

    return new_refs


# ── Entry points ──────────────────────────────────────────────────────────────

def run_triggered_scan(changed_values):
    """
    Called by the 30-second poller when new dataValues are detected.
    Runs outlier + DTP checks scoped to the changed (facility, period) pairs.
    Returns list of new ref_ids.
    """
    changed_pairs = {(v['orgUnit'], v['period']) for v in changed_values}
    print(f'[DQ] triggered scan — {len(changed_pairs)} pair(s): {changed_pairs}')
    new_refs = check_outliers(changed_pairs) + check_dtp(changed_pairs)
    print(f'[DQ] done — {len(new_refs)} new issue(s)')
    return new_refs


def run_full_scan(period=None):
    """
    Manual full scan (triggered by POST /api/scan).
    Runs outlier check across all facilities; optionally adds missing report check.
    Returns list of new ref_ids.
    """
    print('[DQ] full scan')
    new_refs = check_outliers(changed_pairs=None)
    if period:
        new_refs += check_missing_reports(period)
    print(f'[DQ] full scan done — {len(new_refs)} new issue(s)')
    return new_refs
