#!/usr/bin/env python3
"""
Phase 5: Inject synthetic EPI data for all 12 facilities.

Period coverage:
  Baseline : Jan 2024 – Oct 2025 (22 months, clean — used as Z-score baseline)
  Active   : Nov 2025 – Apr 2026  (6 months, seeded DQ issues in Apr 2026)

Dataset: EPI - Routine vaccine delivery (vI4ihClxSm4)
Vaccines: BCG, Penta1 (DTP1), Penta3 (DTP3), MR 1 (MCV1)
Disaggregation: <1 year / 1+ year

Facility volume tiers (monthly BCG <1yr doses):
  Primary Hospital : 280 – 360
  Health Center    :  80 – 115
  Health Post      :  30 –  45

Seeding strategy: each (facility, period) cell gets its own deterministic
seed derived from hashlib.md5(facility_name:period). This means adding or
reordering periods never changes values for other cells.

Three seeded data quality issues in April 2026 (202604):
  1. MISSING REPORT        — Bichena Health Post: no data submitted
  2. OUTLIER               — Limalimo Health Post: BCG <1yr = 350 (~10x normal)
  3. DTP1/DTP3 INCONSISTENCY — Adi Goshu Health Post: Penta3 <1yr (80) > Penta1 <1yr (45)

Output: data_injection_log.json
"""

import json, urllib.request, urllib.error, base64, random, hashlib, sys, os, pathlib
from datetime import datetime, timezone

_env = pathlib.Path(__file__).with_name('.env')
if _env.exists():
    for _line in _env.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith('#') and '=' in _line:
            _k, _, _v = _line.partition('=')
            os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

_creds  = f"{os.environ.get('DHIS2_ADMIN_USER', '')}:{os.environ.get('DHIS2_ADMIN_PASS', '')}"
AUTH    = base64.b64encode(_creds.encode()).decode()
BASE    = os.environ.get('DHIS2_BASE_URL', 'http://localhost:8080/api')
HEADERS = {'Authorization': f'Basic {AUTH}', 'Content-Type': 'application/json'}

ROUTINE_DS = 'vI4ihClxSm4'

# Baseline: 22 months of clean data for robust Z-score statistics
BASELINE_PERIODS = (
    [f'2024{m:02d}' for m in range(1, 13)] +   # Jan–Dec 2024
    [f'2025{m:02d}' for m in range(1, 11)]      # Jan–Oct 2025
)
# Active window: 6 months; seeded DQ issues land in the last period only
ACTIVE_PERIODS = ['202511', '202512', '202601', '202602', '202603', '202604']
PERIODS = BASELINE_PERIODS + ACTIVE_PERIODS

# Data elements (EPI - Routine vaccine delivery dataset)
BCG    = 'WSy7zOZx1Wl'   # BCG doses administered
PENTA1 = 'hJJlOnVOkV2'   # DPT-HepB-HIB 1 (Penta1 / DTP1)
PENTA3 = 'TWWbtMMWD51'   # DPT-HepB-HIB 3 (Penta3 / DTP3)
MR1    = 'kGrnHR9zV2G'   # MR 1 (MCV1 equivalent)

U1  = 'JKuWbG5bWAu'  # <1 year
U1P = 'UIQxmxgioxH'  # 1+ year

# ── Per-cell deterministic seeding ────────────────────────────────────────────

def _seed(fac_name, period):
    """Unique, stable seed for every (facility, period) cell."""
    key = f'{fac_name}:{period}'.encode()
    return int(hashlib.md5(key).hexdigest()[:8], 16)

# ── Volume tiers ──────────────────────────────────────────────────────────────

def baseline(facility_type, fac_name, period):
    """
    Return realistic monthly dose values for a facility type.
    Penta1 ≈ 90% of BCG; Penta3 ≈ 80% of Penta1 (normal 10-20% dropout).
    MR1 ≈ 85% of BCG.
    Seeded per (fac_name, period) so values are stable regardless of
    how many other periods exist in the run.
    """
    random.seed(_seed(fac_name, period))

    if facility_type == 'H':        # Primary hospital
        bcg = random.randint(280, 360)
    elif facility_type == 'HC':     # Health center
        bcg = random.randint(80, 115)
    else:                           # Health post
        bcg = random.randint(30, 45)

    p1  = int(bcg * random.uniform(0.87, 0.93))
    p3  = int(p1  * random.uniform(0.78, 0.85))   # always < Penta1
    mr1 = int(bcg * random.uniform(0.82, 0.90))
    u1p = max(1, int(bcg * random.uniform(0.04, 0.08)))

    return [
        {'dataElement': BCG,    'categoryOptionCombo': U1,  'value': str(bcg)},
        {'dataElement': BCG,    'categoryOptionCombo': U1P, 'value': str(u1p)},
        {'dataElement': PENTA1, 'categoryOptionCombo': U1,  'value': str(p1)},
        {'dataElement': PENTA1, 'categoryOptionCombo': U1P, 'value': str(max(1, int(u1p*0.7)))},
        {'dataElement': PENTA3, 'categoryOptionCombo': U1,  'value': str(p3)},
        {'dataElement': PENTA3, 'categoryOptionCombo': U1P, 'value': str(max(1, int(u1p*0.5)))},
        {'dataElement': MR1,    'categoryOptionCombo': U1,  'value': str(mr1)},
        {'dataElement': MR1,    'categoryOptionCombo': U1P, 'value': str(max(1, int(u1p*0.3)))},
    ]

# ── API helper ────────────────────────────────────────────────────────────────

def post_values(ou_uid, period, values):
    body = json.dumps({
        'dataSet':    ROUTINE_DS,
        'orgUnit':    ou_uid,
        'period':     period,
        'dataValues': values,
    }).encode()
    req = urllib.request.Request(
        f'{BASE}/dataValueSets',
        data=body, headers=HEADERS, method='POST'
    )
    try:
        with urllib.request.urlopen(req) as r:
            resp = json.loads(r.read())
            return True, resp.get('status', 'OK')
    except urllib.error.HTTPError as e:
        return False, json.loads(e.read()).get('message', '')[:100]

# ── Load facilities ───────────────────────────────────────────────────────────

with open('ethiopia_uid_map.json') as f:
    uid_map = json.load(f)

facilities = {}
for code, fac in uid_map['facilities'].items():
    ftype = 'H' if 'Hospital' in fac['name'] else \
            'HC' if 'Health Center' in fac['name'] else 'HP'
    facilities[fac['name']] = {'uid': fac['uid'], 'type': ftype}

# ── Identify facilities for DQ issues ────────────────────────────────────────

MISSING_FAC   = 'Bichena Health Post'    # Issue 1: no report Apr 2026
OUTLIER_FAC   = 'Limalimo Health Post'   # Issue 2: BCG spike Apr 2026
INCONSIST_FAC = 'Adi Goshu Health Post'  # Issue 3: Penta3 > Penta1 Apr 2026

# ── Inject ───────────────────────────────────────────────────────────────────

print('=' * 60)
print('Phase 5: Injecting synthetic EPI data')
print(f'  Facilities       : {len(facilities)}')
print(f'  Baseline periods : {len(BASELINE_PERIODS)}  ({BASELINE_PERIODS[0]} – {BASELINE_PERIODS[-1]})')
print(f'  Active periods   : {len(ACTIVE_PERIODS)}  ({ACTIVE_PERIODS[0]} – {ACTIVE_PERIODS[-1]})')
print(f'  Total periods    : {len(PERIODS)}')
print('=' * 60)

log = {
    'baseline_periods': BASELINE_PERIODS,
    'active_periods':   ACTIVE_PERIODS,
    'facilities': {}, 'dq_issues': [], 'errors': [],
}
total_ok = 0

for fac_name, fac in facilities.items():
    uid   = fac['uid']
    ftype = fac['type']
    log['facilities'][fac_name] = {'uid': uid, 'type': ftype, 'periods': {}}
    print(f'\n  {fac_name} ({ftype})')

    for period in PERIODS:
        # Issue 1: skip Bichena Health Post in Apr 2026 entirely
        if fac_name == MISSING_FAC and period == '202604':
            print(f'    {period}  SKIPPED (seeded missing report)')
            log['facilities'][fac_name]['periods'][period] = 'missing'
            continue

        values = baseline(ftype, fac_name, period)
        issue_label = None

        # Issue 2: BCG spike in Limalimo Health Post, Apr 2026
        if fac_name == OUTLIER_FAC and period == '202604':
            for v in values:
                if v['dataElement'] == BCG and v['categoryOptionCombo'] == U1:
                    v['value'] = '350'   # ~10x normal for a health post
            issue_label = 'OUTLIER seeded: BCG <1yr = 350'

        # Issue 3: Penta3 > Penta1 in Adi Goshu Health Post, Apr 2026
        elif fac_name == INCONSIST_FAC and period == '202604':
            for v in values:
                if v['dataElement'] == PENTA1 and v['categoryOptionCombo'] == U1:
                    v['value'] = '45'
                if v['dataElement'] == PENTA3 and v['categoryOptionCombo'] == U1:
                    v['value'] = '80'   # Penta3 > Penta1 — implausible
            issue_label = 'INCONSISTENCY seeded: Penta3(80) > Penta1(45)'

        ok, status = post_values(uid, period, values)
        if not ok:
            log['errors'].append({'facility': fac_name, 'period': period, 'error': status})
        symbol = 'OK' if ok else 'ERR'
        if issue_label:
            log['facilities'][fac_name]['periods'][period] = f'{symbol.lower()}_with_issue'
            print(f'    {period}  {symbol}  [{issue_label}]')
        else:
            log['facilities'][fac_name]['periods'][period] = symbol
            print(f'    {period}  {symbol}')
        if ok:
            total_ok += 1

# ── Log DQ issues ─────────────────────────────────────────────────────────────

log['dq_issues'] = [
    {
        'type':        'missing_report',
        'facility':    MISSING_FAC,
        'uid':         facilities[MISSING_FAC]['uid'],
        'period':      '202604',
        'description': 'No data submitted for Apr 2026',
    },
    {
        'type':         'outlier',
        'facility':     OUTLIER_FAC,
        'uid':          facilities[OUTLIER_FAC]['uid'],
        'period':       '202604',
        'data_element': 'BCG doses administered (<1yr)',
        'value':        350,
        'normal_range': '30–45',
        'description':  'BCG <1yr = 350 vs. normal 30–45 for a health post (~10x)',
    },
    {
        'type':        'dtp1_dtp3_inconsistency',
        'facility':    INCONSIST_FAC,
        'uid':         facilities[INCONSIST_FAC]['uid'],
        'period':      '202604',
        'penta1_u1':   45,
        'penta3_u1':   80,
        'description': 'Penta3 <1yr (80) > Penta1 <1yr (45) — 3rd dose exceeds 1st dose',
    },
]

log['generated_at'] = datetime.now(timezone.utc).isoformat()

with open('data_injection_log.json', 'w') as f:
    json.dump(log, f, indent=2)

# ── Summary ───────────────────────────────────────────────────────────────────

n_expected = len(facilities) * len(PERIODS) - 1   # -1 for the missing report
print('\n' + '=' * 60)
print('Phase 5 COMPLETE')
print(f'  Data points submitted : {total_ok} / {n_expected}')
print(f'  Errors                : {len(log["errors"])}')
print()
print('  Seeded DQ issues (all in period 202604):')
print(f'  1. MISSING REPORT      — {MISSING_FAC}')
print(f'  2. OUTLIER             — {OUTLIER_FAC}: BCG <1yr = 350 (normal 30-45)')
print(f'  3. DTP INCONSISTENCY   — {INCONSIST_FAC}: Penta3(80) > Penta1(45)')
print()
print('  Saved: data_injection_log.json')
print('=' * 60)
