#!/usr/bin/env python3
"""
Seed the contacts table with the demo notification cascade.

For each person in the AHEAD cascade (facility → woreda → zone → region → national),
this script creates one row linking their DHIS2 username, phone number, and the
org unit they are responsible for.

Usage:
  python3 agent/seed_contacts.py               # uses numbers in this file
  python3 agent/seed_contacts.py --clear       # wipe contacts table first

For a real deployment: edit the CONTACTS list below with actual phone numbers,
then re-run. The script is idempotent (INSERT OR REPLACE).

Phone numbers must be in E.164 format: +251911234567
"""

import sys, pathlib, argparse, json
_HERE = pathlib.Path(__file__).resolve().parent
_ROOT = _HERE.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from db import init_db, get_conn

# ── Edit these for your deployment ───────────────────────────────────────────
#
# covers_uid: the DHIS2 org unit UID this person is responsible for.
# For facility contacts: the facility UID.
# For woreda contacts:   the woreda UID.
# For zone contacts:     the zone UID.
# For region contacts:   the region UID.
# For national contacts: the root UID.
#
# Phone numbers here are placeholders — replace with real numbers before demo.

_UID_MAP_PATH = _ROOT / 'ethiopia_uid_map.json'


def _load_uids():
    if not _UID_MAP_PATH.exists():
        print('WARNING: ethiopia_uid_map.json not found — using placeholder UIDs')
        return {}
    with open(_UID_MAP_PATH) as f:
        return json.load(f)


def build_contacts(uid_map):
    """Build the contacts list from the UID map and demo phone placeholders."""
    eth_uid    = uid_map.get('ethiopia',     {}).get('uid', 'RFhqluFmvRG')
    amhara_uid = uid_map.get('amhara',       {}).get('uid', 'pQp6IYF9XTk')
    ng_uid     = uid_map.get('north_gondar', {}).get('uid', 'vVYYzr9uxpw')
    woreda_uid = uid_map.get('woredas', {}).get('ET0301W01', {}).get('uid', 'JQfos81QQwR')
    fac_uid    = next(
        (f['uid'] for f in uid_map.get('facilities', {}).values()
         if f.get('name') == 'Addi Arekay Health Center'),
        'aV3ume00zx5'
    )

    return [
        {
            'dhis2_username': 'eth_facility_01',
            'phone':          '+16673041318',
            'email':          'almaz.tadesse@example.et',
            'covers_uid':     fac_uid,
            'covers_name':    'Addi Arekay Health Center',
            'level':          'facility',
        },
        {
            'dhis2_username': 'eth_woreda_01',
            'phone':          '+251911000002',   # ← replace with Bekele's real number
            'email':          'bekele.haile@example.et',
            'covers_uid':     woreda_uid,
            'covers_name':    'Addi Arekay Woreda',
            'level':          'woreda',
        },
        {
            'dhis2_username': 'eth_zone_01',
            'phone':          '+251911000003',
            'email':          'tigist.alemu@example.et',
            'covers_uid':     ng_uid,
            'covers_name':    'North Gondar Zone',
            'level':          'zone',
        },
        {
            'dhis2_username': 'eth_regional_01',
            'phone':          '+251911000004',
            'email':          'solomon.worku@example.et',
            'covers_uid':     amhara_uid,
            'covers_name':    'Amhara Region',
            'level':          'region',
        },
        {
            'dhis2_username': 'eth_national_01',
            'phone':          '+251911000005',
            'email':          'meron.gebre@example.et',
            'covers_uid':     eth_uid,
            'covers_name':    'Ethiopia',
            'level':          'national',
        },
    ]


def seed(clear=False):
    init_db()
    uid_map  = _load_uids()
    contacts = build_contacts(uid_map)

    with get_conn() as conn:
        if clear:
            conn.execute('DELETE FROM contacts')
            print('Contacts table cleared.')

        for c in contacts:
            conn.execute("""
                INSERT OR REPLACE INTO contacts
                  (dhis2_username, phone, email, covers_uid, covers_name, level)
                VALUES (:dhis2_username, :phone, :email, :covers_uid, :covers_name, :level)
            """, c)
            print(f'  {c["level"]:<10}  {c["dhis2_username"]:<22}  {c["phone"]}')

    print(f'\n{len(contacts)} contact(s) seeded into agent/agent.db')
    print('Update phone numbers in this script before running the live demo.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--clear', action='store_true', help='Wipe contacts table before seeding')
    args = parser.parse_args()
    seed(clear=args.clear)
