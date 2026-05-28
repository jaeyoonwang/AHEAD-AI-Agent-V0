#!/usr/bin/env python3
"""
Phase 2: Build Ethiopia org unit hierarchy in DHIS2.

Scope:
  Ethiopia (national)
  └── Amhara (region, ET03)
      └── North Gondar (zone, ET0301)
          ├── Addi Arekay Woreda
          ├── Beyeda Woreda
          ├── Janamora Woreda
          ├── Debark Woreda
          └── Dabat Woreda
              └── 3 health facilities each (15 total)

Facility names follow Ethiopian MOH naming conventions.
Source for admin levels: UN OCHA HDX COD-AB April 2025
  https://data.humdata.org/dataset/cod-ab-eth
"""

import json, urllib.request, urllib.error, base64, sys

AUTH   = base64.b64encode(b'admin:district').decode()
BASE   = 'http://localhost:8080/api'
HEADERS = {
    'Authorization': f'Basic {AUTH}',
    'Content-Type': 'application/json',
}

def api_post(path, payload):
    req = urllib.request.Request(
        f'{BASE}{path}',
        data=json.dumps(payload).encode(),
        headers=HEADERS,
        method='POST',
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())

def api_get(path):
    req = urllib.request.Request(f'{BASE}{path}', headers=HEADERS)
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())

def create_org_unit(name, short_name, code, opening_date, parent_uid=None, level=None):
    payload = {
        'name':        name,
        'shortName':   short_name,
        'code':        code,
        'openingDate': opening_date,
    }
    if parent_uid:
        payload['parent'] = {'id': parent_uid}
    resp = api_post('/organisationUnits', payload)
    uid = resp.get('response', {}).get('uid') or resp.get('uid')
    if not uid:
        raise RuntimeError(f'No UID in response for {name}: {resp}')
    print(f'  {"  " * (level or 0)}✓ {name}  [{uid}]')
    return uid

# ── Hierarchy definition ───────────────────────────────────────────────────────

OPENING_DATE = '2010-01-01'

WOREDAS = [
    ('Addi Arekay',  'ET030101'),
    ('Beyeda',       'ET030102'),
    ('Janamora',     'ET030103'),
    ('Debark',       'ET030104'),
    ('Dabat',        'ET030105'),
]

# 3 facilities per woreda — typical Ethiopian naming: HP = Health Post,
# HC = Health Center, Hospital for the largest woreda capital
FACILITIES = {
    'Addi Arekay': [
        ('Addi Arekay Health Center',    'Addi Arekay HC',    'HC'),
        ('Limalimo Health Post',         'Limalimo HP',       'HP'),
        ('Adi Selam Health Post',        'Adi Selam HP',      'HP'),
    ],
    'Beyeda': [
        ('Beyeda Health Center',         'Beyeda HC',         'HC'),
        ('Woken Health Post',            'Woken HP',          'HP'),
        ('Amba Giorgis Health Post',     'Amba Giorgis HP',   'HP'),
    ],
    'Janamora': [
        ('Janamora Health Center',       'Janamora HC',       'HC'),
        ('Adi Goshu Health Post',        'Adi Goshu HP',      'HP'),
        ('Bichena Health Post',          'Bichena HP',        'HP'),
    ],
    'Debark': [
        ('Debark Hospital',              'Debark Hospital',   'Hospital'),
        ('Debark Health Center',         'Debark HC',         'HC'),
        ('Sona Health Post',             'Sona HP',           'HP'),
    ],
    'Dabat': [
        ('Dabat Health Center',          'Dabat HC',          'HC'),
        ('Tikil Dingay Health Post',     'Tikil Dingay HP',   'HP'),
        ('Addis Alem Health Post',       'Addis Alem HP',     'HP'),
    ],
}

# ── Build ──────────────────────────────────────────────────────────────────────

uid_map = {}
print('Building Ethiopia org unit hierarchy...\n')

# Level 1 — Ethiopia
print('Level 1 — National')
eth_uid = create_org_unit(
    name='Ethiopia', short_name='Ethiopia', code='ET',
    opening_date=OPENING_DATE, level=0,
)
uid_map['ethiopia'] = eth_uid

# Level 2 — Amhara
print('\nLevel 2 — Region')
amhara_uid = create_org_unit(
    name='Amhara', short_name='Amhara', code='ET03',
    opening_date=OPENING_DATE, parent_uid=eth_uid, level=1,
)
uid_map['amhara'] = amhara_uid

# Level 3 — North Gondar Zone
print('\nLevel 3 — Zone')
ngondar_uid = create_org_unit(
    name='North Gondar', short_name='N. Gondar', code='ET0301',
    opening_date=OPENING_DATE, parent_uid=amhara_uid, level=2,
)
uid_map['north_gondar'] = ngondar_uid

# Level 4 — Woredas
print('\nLevel 4 — Woredas')
uid_map['woredas'] = {}
for w_name, w_code in WOREDAS:
    uid = create_org_unit(
        name=f'{w_name} Woreda', short_name=w_name, code=w_code,
        opening_date=OPENING_DATE, parent_uid=ngondar_uid, level=3,
    )
    uid_map['woredas'][w_name] = uid

# Level 5 — Facilities
print('\nLevel 5 — Facilities')
uid_map['facilities'] = {}
for w_name, _ in WOREDAS:
    w_uid = uid_map['woredas'][w_name]
    for f_name, f_short, f_type in FACILITIES[w_name]:
        code = f_name.upper().replace(' ', '_')[:50]
        uid = create_org_unit(
            name=f_name, short_name=f_short, code=code,
            opening_date=OPENING_DATE, parent_uid=w_uid, level=4,
        )
        uid_map['facilities'][f_name] = {
            'uid': uid,
            'woreda': w_name,
            'type': f_type,
        }

# ── Save UID map ───────────────────────────────────────────────────────────────

with open('ethiopia_uid_map.json', 'w') as f:
    json.dump(uid_map, f, indent=2)
print(f'\nSaved ethiopia_uid_map.json')

# ── Add Ethiopia to admin user scope (SQL fix) ─────────────────────────────────
print(f'\n⚠  Remember to run the SQL fix so admin can post data:')
print(f'   See dhis2_setup_guide.md, Appendix C.2')
print(f'   Ethiopia UID: {eth_uid}')

# Summary
print('\n' + '='*60)
print('Phase 2 COMPLETE')
print(f'  Ethiopia:      {eth_uid}')
print(f'  Amhara:        {amhara_uid}')
print(f'  North Gondar:  {ngondar_uid}')
print(f'  Woredas:       {len(WOREDAS)}')
print(f'  Facilities:    {len(uid_map["facilities"])}')
print('='*60)
