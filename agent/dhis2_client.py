#!/usr/bin/env python3
"""
DHIS2 REST API client for the AHEAD AI agent.

Uses the agent_service account for all requests (national read scope +
F_DATAVALUE_ADD for write-back). No DQ logic here — only HTTP calls and
response normalization.
"""

import os, pathlib, requests
from datetime import datetime, timezone

# Walk-up .env loader — works regardless of working directory
def _load_env():
    p = pathlib.Path(__file__).resolve().parent
    while p != p.parent:
        env_file = p / '.env'
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, _, v = line.partition('=')
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            return
        p = p.parent

_load_env()

BASE = os.environ.get('DHIS2_BASE_URL', 'http://localhost:8080/api')
AUTH = (
    os.environ.get('AGENT_USER', 'agent_service'),
    os.environ.get('AGENT_PASS', ''),
)

_sess = requests.Session()
_sess.auth = AUTH
_sess.headers.update({'Accept': 'application/json', 'Content-Type': 'application/json'})


def _get(path, params=None):
    r = _sess.get(f'{BASE}{path}', params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def _post(path, body):
    r = _sess.post(f'{BASE}{path}', json=body, timeout=15)
    r.raise_for_status()
    return r.json()


# ── Change detection ──────────────────────────────────────────────────────────

def now_iso():
    """Current UTC time as ISO 8601 string (used to update the poll cursor)."""
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')


def get_changes_since(dataset_uid, root_ou_uid, since_ts):
    """
    Return dataValues modified after since_ts (ISO 8601 string).

    Uses /dataValueSets (not /dataValues) — the sets endpoint supports the
    lastUpdated filter; the singular endpoint does not.
    Returns a list of dicts with keys: dataElement, period, orgUnit, value.
    """
    data = _get('/dataValueSets', params={
        'dataSet':     dataset_uid,
        'orgUnit':     root_ou_uid,
        'children':    'true',
        'lastUpdated': since_ts,
    })
    return data.get('dataValues', [])


# ── Outlier detection (raw data Z-score — no analytics required) ──────────────

def get_outliers(dataset_uid, root_ou_uid, start_date, end_date,
                 z_threshold=3.0, min_periods=3):
    """
    Compute Z-score outliers directly from raw data values.

    Does NOT use the /api/outlierDetection analytics endpoint (which requires
    analytics tables to be rebuilt and special permissions). Instead fetches all
    raw data values and computes per-(facility, data_element, coc) statistics.

    Returns a list of dicts with keys:
      ou, de, coc, pe, value, mean, stdDev, zscore, absDev
    """
    import statistics as _stats
    from collections import defaultdict

    data = _get('/dataValueSets', params={
        'dataSet':   dataset_uid,
        'orgUnit':   root_ou_uid,
        'children':  'true',
        'startDate': start_date,
        'endDate':   end_date,
    })
    raw = data.get('dataValues', [])

    # Group by (org unit, data element, category option combo)
    groups = defaultdict(list)
    for dv in raw:
        try:
            groups[(dv['orgUnit'], dv['dataElement'], dv['categoryOptionCombo'])].append(
                (dv['period'], float(dv['value']))
            )
        except (ValueError, KeyError):
            pass

    outliers = []
    for (ou, de, coc), period_vals in groups.items():
        if len(period_vals) < min_periods:
            continue

        vals = [v for _, v in period_vals]
        mean = _stats.mean(vals)
        try:
            std = _stats.stdev(vals)
        except _stats.StatisticsError:
            continue
        if std == 0:
            continue

        for period, value in period_vals:
            # Compute leave-one-out stats (exclude the candidate value itself)
            # so the reported mean/stdDev reflects the true historical baseline.
            other_vals = [v for p, v in period_vals if p != period]
            if len(other_vals) < min_periods:
                continue
            loo_mean = _stats.mean(other_vals)
            try:
                loo_std = _stats.stdev(other_vals)
            except _stats.StatisticsError:
                continue
            if loo_std == 0:
                continue

            zscore = abs(value - loo_mean) / loo_std
            if zscore >= z_threshold:
                outliers.append({
                    'ou':     ou,
                    'de':     de,
                    'coc':    coc,
                    'pe':     period,
                    'value':  value,
                    'mean':   round(loo_mean, 2),
                    'stdDev': round(loo_std, 2),
                    'zscore': round(zscore, 2),
                    'absDev': round(abs(value - loo_mean), 2),
                })

    return outliers


# ── Data values (for DTP consistency check) ───────────────────────────────────

def get_data_values(dataset_uid, org_unit_uid, period):
    """
    Return all data values for a facility + period as a dict keyed by
    (data_element_uid, category_option_combo_uid) → float value.
    """
    data = _get('/dataValueSets', params={
        'dataSet': dataset_uid,
        'orgUnit': org_unit_uid,
        'period':  period,
    })
    result = {}
    for dv in data.get('dataValues', []):
        try:
            result[(dv['dataElement'], dv['categoryOptionCombo'])] = float(dv['value'])
        except (ValueError, KeyError):
            pass
    return result


# ── Missing report detection ──────────────────────────────────────────────────

def get_complete_registrations(dataset_uid, root_ou_uid, period):
    """
    Return the set of org unit UIDs that have a complete dataset registration
    for the given period (YYYYMM).
    """
    data = _get('/completeDataSetRegistrations', params={
        'dataSet':  dataset_uid,
        'orgUnit':  root_ou_uid,
        'children': 'true',
        'period':   period,
    })
    regs = data.get('completeDataSetRegistrations', [])
    return {r['organisationUnit'] for r in regs}


def get_facilities_in_scope(root_ou_uid, facility_level=5):
    """
    Return all org units at facility_level under root_ou_uid as a list of
    {uid, name} dicts. Used to identify which facilities are missing reports.
    """
    data = _get('/organisationUnits', params={
        'filter':  f'path:like:{root_ou_uid}',
        'level':   facility_level,
        'fields':  'id,displayName',
        'paging':  'false',
    })
    return [{'uid': o['id'], 'name': o['displayName']}
            for o in data.get('organisationUnits', [])]


# ── Write-back ────────────────────────────────────────────────────────────────

def post_data_value(data_element_uid, org_unit_uid, period,
                    category_option_combo_uid, value, comment=None):
    """
    Write a single corrected data value back to DHIS2.
    Uses query parameters — POST /api/dataValues does not accept a JSON body.
    Returns the HTTP response object (201 on success).
    """
    params = {
        'de':    data_element_uid,
        'ou':    org_unit_uid,
        'pe':    period,
        'co':    category_option_combo_uid,
        'value': str(value),
    }
    if comment:
        params['comment'] = comment
    r = _sess.post(f'{BASE}/dataValues', params=params, timeout=15)
    r.raise_for_status()
    return r


def health_check():
    """Return True if DHIS2 is reachable and agent_service can authenticate."""
    try:
        _get('/system/info')
        return True
    except Exception:
        return False
