#!/usr/bin/env python3
"""
Phase 2: Build Ethiopia org unit hierarchy in DHIS2.

Creates:
  Ethiopia                        (national,  level 1)
  └── Amhara                      (region,    level 2)
      └── North Gondar            (zone,      level 3)
          ├── Addi Arekay Woreda  (woreda,    level 4)  3 facilities
          ├── Beyeda Woreda                              2 facilities
          ├── Janamora Woreda                            2 facilities
          ├── Debark Woreda                              3 facilities
          └── Dabat Woreda                               2 facilities

Woreda names are real (OCHA HDX COD-AB, Ethiopia, April 2026).
Facility names follow standard Ethiopian naming conventions.

Output: ethiopia_uid_map.json
"""

import json, urllib.request, urllib.error, base64, random, string, sys

AUTH    = base64.b64encode(b'admin:district').decode()
BASE    = 'http://localhost:8080/api'
HEADERS = {'Authorization': f'Basic {AUTH}', 'Content-Type': 'application/json'}

# ── UID generation ────────────────────────────────────────────────────────────

def gen_uid():
    """DHIS2 UID: one letter followed by 10 alphanumeric characters."""
    chars = string.ascii_letters + string.digits
    return random.choice(string.ascii_letters) + ''.join(random.choices(chars, k=10))

# ── API helpers ───────────────────────────────────────────────────────────────

def post(path, body):
    req = urllib.request.Request(
        f'{BASE}{path}',
        data=json.dumps(body).encode(),
        headers=HEADERS,
        method='POST'
    )
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        err = json.loads(e.read())
        print(f'  ERROR on POST {path}: {err}', file=sys.stderr)
        sys.exit(1)

def create_ou(name, short_name, code, parent_uid=None):
    """Create one org unit; return its UID."""
    uid  = gen_uid()
    body = {
        'id':          uid,
        'name':        name,
        'shortName':   short_name[:50],
        'code':        code,
        'openingDate': '2010-01-01',
    }
    if parent_uid:
        body['parent'] = {'id': parent_uid}

    resp = post('/organisationUnits', body)
    # DHIS2 returns the UID either at root level or inside 'response'
    return resp.get('response', resp).get('uid', uid)

# ── Hierarchy definition ──────────────────────────────────────────────────────

# Each entry: (woreda_name, woreda_code, [(facility_name, facility_short)])
WOREDAS = [
    ('Addi Arekay Woreda', 'ET0301W01', [
        ('Addi Arekay Health Center', 'Addi Arekay HC'),
        ('Adi Goshu Health Post',     'Adi Goshu HP'),
        ('Adi Selam Health Post',     'Adi Selam HP'),
    ]),
    ('Beyeda Woreda', 'ET0301W02', [
        ('Beyeda Health Center',      'Beyeda HC'),
        ('Addis Alem Health Post',    'Addis Alem HP'),
    ]),
    ('Janamora Woreda', 'ET0301W03', [
        ('Janamora Health Center',    'Janamora HC'),
        ('Limalimo Health Post',      'Limalimo HP'),
    ]),
    ('Debark Woreda', 'ET0301W04', [
        ('Debark Primary Hospital',   'Debark Hospital'),
        ('Debark Health Center',      'Debark HC'),
        ('Amba Giorgis Health Post',  'Amba Giorgis HP'),
    ]),
    ('Dabat Woreda', 'ET0301W05', [
        ('Dabat Health Center',       'Dabat HC'),
        ('Bichena Health Post',       'Bichena HP'),
    ]),
]

# ── Build ─────────────────────────────────────────────────────────────────────

print('=' * 60)
print('Phase 2: Building Ethiopia EPI org unit hierarchy')
print('=' * 60)

uid_map = {}

# Level 1 — Ethiopia
print('\n[Level 1] Ethiopia')
eth_uid = create_ou('Ethiopia', 'Ethiopia', 'ETH')
uid_map['ethiopia'] = {'uid': eth_uid, 'name': 'Ethiopia', 'level': 1}
print(f'  Ethiopia → {eth_uid}')

# Level 2 — Amhara Region
print('\n[Level 2] Amhara Region')
amhara_uid = create_ou('Amhara', 'Amhara', 'ET03', parent_uid=eth_uid)
uid_map['amhara'] = {'uid': amhara_uid, 'name': 'Amhara', 'level': 2}
print(f'  Amhara → {amhara_uid}')

# Level 3 — North Gondar Zone
print('\n[Level 3] North Gondar Zone')
ng_uid = create_ou('North Gondar', 'N. Gondar', 'ET0301', parent_uid=amhara_uid)
uid_map['north_gondar'] = {'uid': ng_uid, 'name': 'North Gondar', 'level': 3}
print(f'  North Gondar → {ng_uid}')

# Levels 4 + 5 — Woredas and Facilities
uid_map['woredas']    = {}
uid_map['facilities'] = {}

print('\n[Levels 4–5] Woredas and facilities')
for woreda_name, woreda_code, facilities in WOREDAS:
    w_uid = create_ou(woreda_name, woreda_name[:50], woreda_code, parent_uid=ng_uid)
    uid_map['woredas'][woreda_code] = {
        'uid': w_uid, 'name': woreda_name, 'level': 4, 'code': woreda_code
    }
    print(f'\n  {woreda_name} → {w_uid}')

    for fac_name, fac_short in facilities:
        fac_code = woreda_code + '_' + fac_name.upper().replace(' ', '_')[:20]
        f_uid = create_ou(fac_name, fac_short, fac_code, parent_uid=w_uid)
        uid_map['facilities'][fac_code] = {
            'uid': f_uid, 'name': fac_name, 'level': 5,
            'code': fac_code, 'woreda': woreda_name, 'woreda_uid': w_uid
        }
        print(f'    {fac_name} → {f_uid}')

# ── Save ──────────────────────────────────────────────────────────────────────

with open('ethiopia_uid_map.json', 'w') as f:
    json.dump(uid_map, f, indent=2)

# ── Summary ───────────────────────────────────────────────────────────────────

n_woredas   = len(uid_map['woredas'])
n_facilities = len(uid_map['facilities'])
total = 3 + n_woredas + n_facilities  # national + region + zone + woredas + facilities

print('\n' + '=' * 60)
print('Phase 2 COMPLETE')
print(f'  National + Region + Zone : 3')
print(f'  Woredas                  : {n_woredas}')
print(f'  Facilities               : {n_facilities}')
print(f'  Total org units          : {total}')
print(f'  Saved                    : ethiopia_uid_map.json')
print('=' * 60)
print()
print('NEXT STEP — apply admin scope SQL fix:')
print(f"  docker compose exec db psql -U dhis -d dhis2 -c \\")
print(f"    \"INSERT INTO usermembership(userinfoid,organisationunitid) \\")
print(f"     SELECT u.userinfoid,o.organisationunitid \\")
print(f"     FROM userinfo u,organisationunit o \\")
print(f"     WHERE u.username='admin' AND o.uid='{eth_uid}';\"")
