#!/usr/bin/env python3
"""
Phase 3: Assign EPI datasets to all facilities.

Both EPI datasets are assigned to every level-5 org unit so that
data entry forms are available to facility workers.

Datasets assigned:
  vI4ihClxSm4  EPI - Routine vaccine delivery
  jqSaKxtj8IA  EPI - Stock
"""

import json, urllib.request, urllib.error, base64, sys, os, pathlib

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

DATASETS = [
    ('vI4ihClxSm4', 'EPI - Routine vaccine delivery'),
    ('jqSaKxtj8IA', 'EPI - Stock'),
]

with open('ethiopia_uid_map.json') as f:
    uid_map = json.load(f)

facilities = uid_map['facilities']

print('=' * 60)
print('Phase 3: Assigning EPI datasets to facilities')
print('=' * 60)
print(f'\nFacilities: {len(facilities)}')
print(f'Datasets:   {len(DATASETS)}')
print(f'Total assignments: {len(facilities) * len(DATASETS)}\n')

errors = 0

for ds_id, ds_name in DATASETS:
    print(f'[{ds_name}]')
    for fac_code, fac in facilities.items():
        fac_uid  = fac['uid']
        fac_name = fac['name']

        # POST /api/dataSets/{ds}/organisationUnits/{ou}
        # Returns 200 with empty body on success — do not try to parse JSON
        req = urllib.request.Request(
            f'{BASE}/dataSets/{ds_id}/organisationUnits/{fac_uid}',
            data=b'',
            headers=HEADERS,
            method='POST'
        )
        try:
            with urllib.request.urlopen(req) as r:
                r.read()  # drain (empty body)
            print(f'  OK  {fac_name}')
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            print(f'  ERR {fac_name}: HTTP {e.code} {body[:100]}')
            errors += 1
    print()

print('=' * 60)
print('Phase 3 COMPLETE' if errors == 0 else f'Phase 3 DONE WITH {errors} ERROR(S)')
print(f'  Assignments made: {len(facilities) * len(DATASETS) - errors}')
print('=' * 60)
