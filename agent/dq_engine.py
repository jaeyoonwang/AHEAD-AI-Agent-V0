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


def _skip_or_supersede(conn, facility_uid, period, data_element, issue_type):
    """
    Check for an existing open issue for the same (facility, period, element, type).

    Returns True  → skip: user is already mid-conversation (awaiting_followup or
                    awaiting_confirmation), so don't disrupt an active exchange.
    Returns False → proceed: either no existing issue, or the existing issue has
                    received no reply yet (awaiting_option) and is superseded —
                    the old issue is closed and a fresh one will be created.

    Superseding on resubmission means that re-entering data in DHIS2 always
    re-triggers the full alert flow, which is the expected demo behaviour.
    """
    existing = conn.execute(
        "SELECT ref_id FROM issues "
        "WHERE facility_uid=? AND period=? AND data_element IS ? AND issue_type=? "
        "AND status NOT IN ('resolved', 'ignored') LIMIT 1",
        (facility_uid, period, data_element, issue_type)
    ).fetchone()

    if not existing:
        return False  # no existing issue — proceed normally

    ref = existing['ref_id']
    conv = conn.execute(
        "SELECT state FROM conversations WHERE issue_ref_id=? AND state != 'closed' "
        "ORDER BY updated_at DESC LIMIT 1",
        (ref,)
    ).fetchone()

    if conv and conv['state'] in ('awaiting_followup', 'awaiting_confirmation'):
        return True  # user is mid-conversation — leave it alone

    # No response yet (awaiting_option) or no conversation — supersede
    conn.execute(
        "UPDATE issues SET status='resolved', "
        "resolution_notes='Superseded: new data submitted before response' "
        "WHERE ref_id=?", (ref,)
    )
    conn.execute(
        "UPDATE conversations SET state='closed', updated_at=CURRENT_TIMESTAMP "
        "WHERE issue_ref_id=? AND state != 'closed'", (ref,)
    )
    print(f'[DQ] superseded stale issue {ref} — new submission detected')
    return False  # proceed: create a fresh issue


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

    The AHEAD guide specifies 5 detection methods (SD, MAD, Median AD, Lowess,
    Absolute Diff). This MVP implements methods 1 (Z-score/SD) and 5 (absolute
    difference). A value is flagged if EITHER method fires — matching the guide's
    "1+ methods = possible outlier" tier. Thresholds are config; see OUTLIER_Z_THRESHOLD
    and OUTLIER_ABS_THRESHOLD in config.py.

    Returns list of newly created ref_ids.
    """
    start = (date.today() - timedelta(days=900)).strftime('%Y-%m-%d')  # ~2.5 years
    # Use last day of current month — DHIS2 excludes monthly periods whose end
    # date is after endDate, so using today would cut off the current period.
    _today = date.today()
    _next  = (_today.replace(day=28) + timedelta(days=4)).replace(day=1)
    end    = (_next - timedelta(days=1)).strftime('%Y-%m-%d')

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

            # Require BOTH method 1 (Z-score, already filtered by get_outliers()) AND
            # method 5 (absolute diff). Using OR would flood small health posts:
            # a facility with mean BCG=2 doses naturally produces Z-scores > 2 from
            # a single-dose swing, but abs_diff=1 is not a real data quality issue.
            # AND logic ensures only genuinely large deviations are flagged.
            if value is not None and mean is not None:
                if abs(value - mean) < cfg.OUTLIER_ABS_THRESHOLD:
                    continue

            if _skip_or_supersede(conn, ou_uid, period, de_name, 'outlier'):
                continue

            # Look up facility name from cached hierarchy (raw API doesn't return ouName)
            hier = conn.execute(
                'SELECT facility_name FROM org_unit_hierarchy WHERE facility_uid=?', (ou_uid,)
            ).fetchone()
            fac_name = hier['facility_name'] if hier else ou_uid

            expected_low  = round(mean - cfg.OUTLIER_Z_THRESHOLD * std_dev, 1) if mean and std_dev else None
            expected_high = round(mean + cfg.OUTLIER_Z_THRESHOLD * std_dev, 1) if mean and std_dev else None

            ref = _create_issue(
                conn, 'outlier', ou_uid, fac_name, period,
                de_name, value, expected_low, expected_high
            )
            new_refs.append(ref)
            print(f'[DQ] outlier: {ref}  {fac_name} {period} {de_name}={value} (mean={mean:.1f})')

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

            if _skip_or_supersede(conn, ou_uid, period, 'DTP', 'dtp'):
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
            if _skip_or_supersede(conn, fac['uid'], period, None, 'missing'):
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
