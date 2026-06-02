#!/usr/bin/env python3
"""
AHEAD AI Agent — main entry point.

Flask web app on port 5001:
  POST /webhook/sms  — Twilio inbound SMS webhook
  GET  /issues       — issue log dashboard
  POST /api/scan     — manual DQ trigger (demo use)
  GET  /api/health   — liveness check

APScheduler background jobs:
  poll_changes       — every 30 seconds; triggers DQ when DHIS2 data changes
  check_missing      — daily at 08:00 EAT; flags facilities with no monthly report
  process_timers     — every 30 minutes; retries and escalates stale issues
  monthly_summary    — 1st of each month at 08:00 EAT; sends digest to national contact

Run from project root:
  python3 agent/app.py
"""

import sys, os, pathlib, json

_HERE = pathlib.Path(__file__).resolve().parent
_ROOT = _HERE.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

# Load .env before any module-level env reads
def _load_env():
    p = _ROOT
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

from flask import Flask, request, jsonify, Response
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

import config as cfg
import dhis2_client as dc
import dq_engine
import state_machine as sm
from db import init_db, get_conn, seed_hierarchy

app = Flask(__name__)

# ── Startup ───────────────────────────────────────────────────────────────────

def _startup():
    """Initialise the database and hierarchy cache on first run."""
    init_db()

    uid_map_path = _ROOT / 'ethiopia_uid_map.json'
    if uid_map_path.exists():
        with open(uid_map_path) as f:
            seed_hierarchy(json.load(f))
        print('[APP] org_unit_hierarchy seeded from ethiopia_uid_map.json')
    else:
        print('[APP] WARNING: ethiopia_uid_map.json not found — run dhis2/build_ethiopia.py first')

    if dc.health_check():
        print('[APP] DHIS2 reachable — agent_service authenticated')
    else:
        print('[APP] WARNING: DHIS2 not reachable — check DHIS2_BASE_URL and AGENT credentials')


# ── APScheduler jobs ──────────────────────────────────────────────────────────

def _job_poll_changes():
    """Every 30 seconds: check for new data values; trigger DQ if changed."""
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM poll_state WHERE key='last_checked'").fetchone()
        since = row['value'] if row else '2024-01-01T00:00:00'

    try:
        changes = dc.get_changes_since(cfg.ROUTINE_DATASET_UID, cfg.ROOT_ORG_UNIT_UID, since)
    except Exception as e:
        print(f'[POLL] DHIS2 error: {e}')
        return

    # Advance the cursor regardless of whether changes were found
    now = dc.now_iso()
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO poll_state (key, value) VALUES ('last_checked', ?)",
            (now,)
        )

    if not changes:
        return

    print(f'[POLL] {len(changes)} change(s) detected — running DQ scan')
    new_refs = dq_engine.run_triggered_scan(changes)
    for ref_id in new_refs:
        sm.notify_issue(ref_id)


def _job_check_missing():
    """Daily 08:00 EAT: flag facilities with no complete registration for previous month."""
    from datetime import date
    today = date.today()
    if today.day < cfg.MISSING_REPORT_START_DAY:
        return  # too early this month
    prev_month = (today.replace(day=1) - __import__('datetime').timedelta(days=1))
    period = prev_month.strftime('%Y%m')
    print(f'[MISSING] running check for period {period}')
    new_refs = dq_engine.check_missing_reports(period)
    for ref_id in new_refs:
        sm.notify_issue(ref_id)


def _job_process_timers():
    """Every 30 minutes: retry and escalate stale issues."""
    sm.escalate_due_issues()


def _job_monthly_summary():
    """1st of month 08:00 EAT: send digest to national contact (stub for Phase 2)."""
    from datetime import date
    prev_month = (date.today().replace(day=1) - __import__('datetime').timedelta(days=1))
    period = prev_month.strftime('%Y%m')
    print(f'[SUMMARY] monthly digest for {period} — Phase 2 implementation pending')


def _start_scheduler():
    sched = BackgroundScheduler(timezone='Africa/Addis_Ababa')
    sched.add_job(_job_poll_changes,    'interval', seconds=cfg.POLL_INTERVAL_SEC, id='poll')
    sched.add_job(_job_check_missing,   CronTrigger(hour=8, minute=0),   id='missing')
    sched.add_job(_job_process_timers,  'interval', minutes=30,          id='timers')
    sched.add_job(_job_monthly_summary, CronTrigger(day=1, hour=8),      id='monthly')
    sched.start()
    print(f'[APP] scheduler started — poll every {cfg.POLL_INTERVAL_SEC}s')
    return sched


# ── Flask routes ──────────────────────────────────────────────────────────────

@app.route('/webhook/sms', methods=['POST'])
def webhook_sms():
    """
    Twilio inbound SMS webhook.
    Twilio sends form-encoded POST with From and Body fields.
    Responds with TwiML (empty <Response> if no reply needed).
    """
    from_phone = request.form.get('From', '')
    body       = request.form.get('Body', '').strip()

    print(f'[WEBHOOK] inbound from {from_phone[:7]}***: {body[:60]}')
    reply = sm.handle_inbound(from_phone, body)

    if reply:
        twiml = f'<?xml version="1.0"?><Response><Message>{reply}</Message></Response>'
    else:
        twiml = '<?xml version="1.0"?><Response></Response>'

    return Response(twiml, mimetype='text/xml')


@app.route('/api/scan', methods=['POST'])
def api_scan():
    """
    Manual DQ trigger for demo use.
    Body (JSON, all optional): {"period": "202606"}
    Runs a full outlier scan + optional missing report check.
    """
    data   = request.get_json(silent=True) or {}
    period = data.get('period')

    new_refs = dq_engine.run_full_scan(period)
    for ref_id in new_refs:
        sm.notify_issue(ref_id)

    return jsonify({'new_issues': new_refs, 'count': len(new_refs)})


@app.route('/api/health', methods=['GET'])
def api_health():
    dhis2_ok = dc.health_check()
    with get_conn() as conn:
        issue_count = conn.execute("SELECT COUNT(*) FROM issues").fetchone()[0]
    return jsonify({'dhis2': dhis2_ok, 'open_issues': issue_count})


@app.route('/issues', methods=['GET'])
def issue_log():
    """Simple HTML issue log dashboard."""
    with get_conn() as conn:
        issues = conn.execute(
            "SELECT * FROM issues ORDER BY created_at DESC LIMIT 200"
        ).fetchall()

    rows = []
    for i in issues:
        status_color = {
            'open': '#e67e22', 'resolved': '#27ae60',
            'escalated': '#c0392b', 'ignored': '#7f8c8d'
        }.get(i['status'], '#333')

        element = i['data_element'] or '—'
        value   = f'{int(i["flagged_value"])}' if i['flagged_value'] else '—'
        expected = ''
        if i['expected_low'] is not None and i['expected_high'] is not None:
            if i['issue_type'] == 'dtp':
                expected = f'Penta1={int(i["expected_low"])}'
            else:
                expected = f'{int(i["expected_low"])}–{int(i["expected_high"])}'

        rows.append(f"""
          <tr>
            <td><code>{i['ref_id']}</code></td>
            <td>{i['issue_type'].upper()}</td>
            <td>{i['facility_name']}</td>
            <td>{i['period']}</td>
            <td>{element}</td>
            <td>{value}</td>
            <td>{expected}</td>
            <td style="color:{status_color};font-weight:bold">{i['status'].upper()}</td>
            <td>{i['cascade_level']}</td>
            <td style="font-size:0.85em;color:#555">{i['resolution_notes'] or ''}</td>
          </tr>""")

    table = '\n'.join(rows) if rows else '<tr><td colspan="10">No issues yet.</td></tr>'

    html = f"""<!DOCTYPE html>
<html><head>
  <title>AHEAD DQ Issue Log</title>
  <meta charset="utf-8">
  <style>
    body {{ font-family: -apple-system, sans-serif; padding: 2rem; background: #f4f6f8; }}
    h1   {{ color: #2c3e50; margin-bottom: 0.25rem; }}
    p    {{ color: #7f8c8d; margin-top: 0; }}
    table {{ width: 100%; border-collapse: collapse; background: #fff;
             border-radius: 8px; overflow: hidden;
             box-shadow: 0 1px 4px rgba(0,0,0,.1); }}
    th   {{ background: #2c3e50; color: #fff; padding: .75rem 1rem; text-align: left;
            font-size: .8rem; letter-spacing: .05em; text-transform: uppercase; }}
    td   {{ padding: .65rem 1rem; border-bottom: 1px solid #ecf0f1; font-size: .9rem; }}
    tr:last-child td {{ border-bottom: none; }}
    tr:hover td {{ background: #f8f9fa; }}
    code {{ background: #ecf0f1; padding: 2px 6px; border-radius: 3px; }}
  </style>
</head><body>
  <h1>AHEAD DQ Issue Log</h1>
  <p>All detected data quality issues and their resolution status.</p>
  <table>
    <thead>
      <tr>
        <th>Ref ID</th><th>Type</th><th>Facility</th><th>Period</th>
        <th>Element</th><th>Value</th><th>Expected</th>
        <th>Status</th><th>Level</th><th>Resolution</th>
      </tr>
    </thead>
    <tbody>{table}</tbody>
  </table>
</body></html>"""

    return Response(html, mimetype='text/html')


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    _startup()
    _sched = _start_scheduler()
    try:
        app.run(host='0.0.0.0', port=5001, debug=False, use_reloader=False)
    finally:
        _sched.shutdown()
