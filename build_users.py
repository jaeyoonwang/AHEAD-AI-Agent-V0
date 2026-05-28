#!/usr/bin/env python3
"""
Phase 4: Create role-based user accounts replicating the AHEAD cascade.

Two user roles:
  EPI Data Entry  — facility and woreda workers who enter monthly reports
  EPI Data Viewer — zone, region, and national staff who review and analyse

Five users:
  eth_facility_01   scoped to Addi Arekay Health Center  (data entry)
  eth_woreda_01     scoped to Addi Arekay Woreda          (data entry)
  eth_zone_01       scoped to North Gondar Zone            (view only)
  eth_regional_01   scoped to Amhara Region                (view only)
  eth_national_01   scoped to Ethiopia                     (view only)

All users share password: Ethiopia@2024
"""

import json, urllib.request, urllib.error, base64, sys, os

_creds   = f"{os.environ.get('DHIS2_ADMIN_USER', '')}:{os.environ.get('DHIS2_ADMIN_PASS', '')}"
AUTH     = base64.b64encode(_creds.encode()).decode()
BASE     = os.environ.get('DHIS2_BASE_URL', 'http://localhost:8080/api')
HEADERS  = {'Authorization': f'Basic {AUTH}', 'Content-Type': 'application/json'}

PASSWORD = os.environ.get('DHIS2_USER_PASSWORD', '')

def get(path):
    req = urllib.request.Request(f'{BASE}{path}',
                                  headers={'Authorization': f'Basic {AUTH}'})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())

def post(path, body):
    req = urllib.request.Request(
        f'{BASE}{path}',
        data=json.dumps(body).encode(),
        headers=HEADERS,
        method='POST'
    )
    try:
        with urllib.request.urlopen(req) as r:
            return True, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return False, json.loads(e.read())

with open('ethiopia_uid_map.json') as f:
    uid_map = json.load(f)

eth_uid           = uid_map['ethiopia']['uid']
amhara_uid        = uid_map['amhara']['uid']
ng_uid            = uid_map['north_gondar']['uid']
arekay_woreda_uid = uid_map['woredas']['ET0301W01']['uid']
arekay_hc_uid     = next(f['uid'] for f in uid_map['facilities'].values()
                          if f['name'] == 'Addi Arekay Health Center')

print('=' * 60)
print('Phase 4: Creating role-based user accounts')
print('=' * 60)

# ── User roles ────────────────────────────────────────────────────────────────

print('\n[Step 1] Creating user roles')

ok, resp = post('/userRoles', {
    'name': 'EPI Data Entry',
    'description': 'Facility and woreda staff — monthly EPI data entry',
    'authorities': [
        'M_dhis-web-dataentry',
        'M_dhis-web-dashboard',
        'M_dhis-web-pivot',
        'M_dhis-web-visualizer',
        'M_dhis-web-maps',
        'F_DATAVALUE_ADD',
        'F_DATAVALUE_DELETE',
    ]
})
entry_role_uid = resp.get('response', resp).get('uid')
print(f'  EPI Data Entry  → {entry_role_uid}')

ok, resp = post('/userRoles', {
    'name': 'EPI Data Viewer',
    'description': 'Zone, region, national staff — view and analyse EPI data',
    'authorities': [
        'M_dhis-web-dashboard',
        'M_dhis-web-pivot',
        'M_dhis-web-visualizer',
        'M_dhis-web-maps',
        'M_dhis-web-data-quality',
    ]
})
viewer_role_uid = resp.get('response', resp).get('uid')
print(f'  EPI Data Viewer → {viewer_role_uid}')

# ── Users ─────────────────────────────────────────────────────────────────────

print('\n[Step 2] Creating users')

users = [
    dict(username='eth_facility_01', firstName='Almaz',   surname='Tadesse',
         role=entry_role_uid,  entry_ou=arekay_hc_uid,     view_ou=arekay_hc_uid),
    dict(username='eth_woreda_01',   firstName='Bekele',  surname='Haile',
         role=entry_role_uid,  entry_ou=arekay_woreda_uid,  view_ou=arekay_woreda_uid),
    dict(username='eth_zone_01',     firstName='Tigist',  surname='Alemu',
         role=viewer_role_uid, entry_ou=None,               view_ou=ng_uid),
    dict(username='eth_regional_01', firstName='Solomon', surname='Worku',
         role=viewer_role_uid, entry_ou=None,               view_ou=amhara_uid),
    dict(username='eth_national_01', firstName='Meron',   surname='Gebre',
         role=viewer_role_uid, entry_ou=None,               view_ou=eth_uid),
]

created = []
for u in users:
    body = {
        'username':  u['username'],
        'password':  PASSWORD,
        'firstName': u['firstName'],
        'surname':   u['surname'],
        'userRoles': [{'id': u['role']}],
        'dataViewOrganisationUnits': [{'id': u['view_ou']}],
    }
    if u['entry_ou']:
        body['organisationUnits'] = [{'id': u['entry_ou']}]

    ok, resp = post('/users', body)
    uid = resp.get('response', resp).get('uid', '?')
    print(f'  {"OK" if ok else "ERR"}  {u["username"]} → {uid}')
    if not ok:
        print(f'       {resp}')
    else:
        created.append(u['username'])

# Save role UIDs into uid_map
uid_map['user_roles'] = {
    'entry':  {'uid': entry_role_uid,  'name': 'EPI Data Entry'},
    'viewer': {'uid': viewer_role_uid, 'name': 'EPI Data Viewer'},
}
with open('ethiopia_uid_map.json', 'w') as f:
    json.dump(uid_map, f, indent=2)

print('\n' + '=' * 60)
print('Phase 4 COMPLETE')
print(f'  Roles created: 2    Users created: {len(created)}')
print()
print(f'  {"Username":<22} {"Password":<16} Scope')
print(f'  {"-"*58}')
scopes = ['Addi Arekay Health Center', 'Addi Arekay Woreda',
          'North Gondar Zone', 'Amhara Region', 'Ethiopia (national)']
for u, scope in zip(users, scopes):
    print(f'  {u["username"]:<22} {PASSWORD:<16} {scope}')
print('=' * 60)
