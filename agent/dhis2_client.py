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

    Used by the 30-second poller: if this returns anything, a DQ scan fires.
    Returns a list of dicts with keys: dataElement, period, orgUnit, value.
    """
    data = _get('/dataValues', params={
        'dataSet':     dataset_uid,
        'orgUnit':     root_ou_uid,
        'children':    'true',
        'lastUpdated': since_ts,
        'fields':      'dataElement,period,orgUnit,value,lastUpdated',
    })
    return data.get('dataValues', [])


# ── Outlier detection ─────────────────────────────────────────────────────────

def get_outliers(dataset_uid, root_ou_uid, start_date, end_date,
                 z_threshold=3.0, max_results=500):
    """
    Call the DHIS2 built-in Z-score outlier detection API.

    Returns a list of dicts, each with:
      de (data element UID), ou (org unit UID), ouName, pe (period YYYYMM),
      value, mean, stdDev, zscore, absDev
    """
    data = _get('/outlierDetection', params={
        'ds':         dataset_uid,
        'ou':         root_ou_uid,
        'startDate':  start_date,
        'endDate':    end_date,
        'algorithm':  'Z_SCORE',
        'threshold':  z_threshold,
        'maxResults': max_results,
    })
    return data.get('outlierValues', [])


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
    value should be a number or string; it will be cast to str for the API.
    Returns the DHIS2 import summary dict.
    """
    payload = {
        'de':    data_element_uid,
        'ou':    org_unit_uid,
        'pe':    period,
        'co':    category_option_combo_uid,
        'value': str(value),
    }
    if comment:
        payload['comment'] = comment
    return _post('/dataValues', payload)


def health_check():
    """Return True if DHIS2 is reachable and agent_service can authenticate."""
    try:
        _get('/system/info')
        return True
    except Exception:
        return False
