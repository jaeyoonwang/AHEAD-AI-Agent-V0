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

    # Seed poll cursor to now if this is a fresh DB.
    # Without this, the first poll fetches all historical data as "changes"
    # and runs DQ on every (facility, period) pair since 2024 — generating
    # false positive alerts on natural variation in the baseline data.
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM poll_state WHERE key='last_checked'").fetchone()
        if not row:
            now = dc.now_iso()
            conn.execute(
                "INSERT INTO poll_state (key, value) VALUES ('last_checked', ?)", (now,)
            )
            print(f'[APP] poll cursor initialised to {now} (first run)')


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
    from_phone = request.form.get('From', '').replace('whatsapp:', '')
    body       = request.form.get('Body', '').strip()

    print(f'[WEBHOOK] inbound from {from_phone[:7]}***: {body[:60]}')
    reply = sm.handle_inbound(from_phone, body)

    if reply:
        import html as _html
        twiml = f'<?xml version="1.0"?><Response><Message>{_html.escape(reply)}</Message></Response>'
    else:
        twiml = '<?xml version="1.0"?><Response></Response>'

    return Response(twiml, mimetype='text/xml')


@app.route('/api/reset-demo', methods=['POST'])
def api_reset_demo():
    """
    Full demo reset: clears agent DB state AND deletes June 2026 data values
    from DHIS2 for the demo facility (Addi Arekay HC).

    DHIS2 does not update lastUpdated when you save an identical value, so the
    poll cannot detect a 'resubmission' of the same number. Clearing the DHIS2
    values first ensures every demo run starts from an empty form — entering
    BCG=970 is always a genuine first write with a fresh lastUpdated.

    Call this instead of the manual python3 reset script between demo runs.
    """
    demo_facility = 'aV3ume00zx5'   # Addi Arekay Health Center
    demo_period   = '202606'         # June 2026

    errors = []

    # 1. Delete all data values for the demo facility/period from DHIS2
    for de_uid in cfg.DATA_ELEMENTS.values():
        for coc_uid in cfg.CATEGORY_OPTION_COMBOS.values():
            try:
                dc._sess.delete(f'{dc.BASE}/dataValues', params={
                    'de': de_uid, 'ou': demo_facility,
                    'pe': demo_period, 'co': coc_uid,
                }, timeout=10)
            except Exception as e:
                errors.append(str(e))

    # 2. Reset agent DB and advance poll cursor to now
    #    (clearing poll_state would cause the next poll to default to 2024-01-01
    #    and flood with historical data — set to now instead)
    now = dc.now_iso()
    with get_conn() as conn:
        conn.execute('DELETE FROM conversations')
        conn.execute('DELETE FROM issues')
        conn.execute(
            "INSERT OR REPLACE INTO poll_state (key, value) VALUES ('last_checked', ?)", (now,)
        )

    print(f'[APP] demo reset — DHIS2 Jun 2026 cleared, DB reset, poll cursor → {now}')
    return jsonify({'ok': True, 'dhis2_errors': errors})


@app.route('/api/resend/<ref_id>', methods=['POST'])
def api_resend(ref_id):
    """
    Resend the WhatsApp/SMS notification for an open issue.
    Useful when the sandbox session has expired or a message wasn't delivered.
    Closes any existing open conversation first so a fresh one is created.
    """
    with get_conn() as conn:
        issue = conn.execute('SELECT * FROM issues WHERE ref_id=?', (ref_id,)).fetchone()
        if not issue:
            return jsonify({'error': 'not found'}), 404
        if issue['status'] in ('resolved', 'ignored'):
            return jsonify({'error': 'issue already closed'}), 400
        conn.execute(
            "UPDATE conversations SET state='closed', updated_at=CURRENT_TIMESTAMP "
            "WHERE issue_ref_id=? AND state != 'closed'",
            (ref_id,)
        )
    sm.notify_issue(ref_id)
    print(f'[APP] resend triggered for {ref_id}')
    return jsonify({'ok': True, 'ref_id': ref_id})


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
    """HTML issue log dashboard with live conversation state."""
    with get_conn() as conn:
        rows_raw = conn.execute("""
            SELECT i.*,
                   c.state      AS conv_state,
                   c.updated_at AS conv_updated_at
            FROM issues i
            LEFT JOIN (
                SELECT issue_ref_id,
                       state,
                       MAX(updated_at) AS updated_at
                FROM conversations
                GROUP BY issue_ref_id
            ) c ON i.ref_id = c.issue_ref_id
            ORDER BY i.created_at DESC
            LIMIT 200
        """).fetchall()

    def display_status(issue_status, conv_state):
        if issue_status == 'resolved':   return 'RESOLVED',     '#27ae60'
        if issue_status == 'ignored':    return 'CONFIRMED OK', '#7f8c8d'
        if issue_status == 'escalated':  return 'ESCALATED',    '#c0392b'
        if conv_state == 'awaiting_confirmation': return 'CONFIRMING',  '#8e44ad'
        if conv_state == 'awaiting_followup':     return 'IN PROGRESS', '#2980b9'
        if conv_state == 'awaiting_option':       return 'NOTIFIED',    '#d35400'
        return 'OPEN', '#e67e22'

    def fmt_ts(ts):
        """Format a SQLite timestamp string to 'Jun 4, 17:35'."""
        if not ts:
            return ''
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(ts.replace('T', ' ').split('.')[0])
            months = ['Jan','Feb','Mar','Apr','May','Jun',
                      'Jul','Aug','Sep','Oct','Nov','Dec']
            return f'{months[dt.month-1]} {dt.day}, {dt.strftime("%H:%M")}'
        except Exception:
            return ts[:16]

    def status_ts(i):
        """Pick the most relevant timestamp for the current status."""
        status = i['status']
        conv   = i['conv_state']
        if status == 'resolved':   return fmt_ts(i['resolved_at'])
        if status in ('ignored', 'escalated'): return fmt_ts(i['resolved_at'])
        if conv in ('awaiting_followup', 'awaiting_confirmation'):
            return fmt_ts(i['conv_updated_at'])
        if conv == 'awaiting_option': return fmt_ts(i['notified_at'])
        return fmt_ts(i['created_at'])

    rows = []
    for i in rows_raw:
        label, color = display_status(i['status'], i['conv_state'])
        ts            = status_ts(i)
        is_open       = i['status'] not in ('resolved', 'ignored', 'escalated')

        element  = i['data_element'] or '—'
        value    = f'{int(i["flagged_value"])}' if i['flagged_value'] else '—'
        expected = ''
        if i['expected_low'] is not None and i['expected_high'] is not None:
            if i['issue_type'] == 'dtp':
                expected = f'Penta1={int(i["expected_low"])}'
            else:
                lo = max(0, int(i['expected_low']))
                expected = f'{lo}–{int(i["expected_high"])}'

        resend_btn = (
            f'<form method="post" action="/api/resend/{i["ref_id"]}" style="display:inline">'
            f'<button class="resend-btn" title="Resend WhatsApp alert">↺ Resend</button></form>'
            if is_open else ''
        )

        status_cell = (
            f'<span style="color:{color};font-weight:bold">{label}</span>'
            f'<br><span style="font-size:0.78em;color:#999">{ts}</span>'
        )

        rows.append(f"""
          <tr>
            <td><code>{i['ref_id']}</code></td>
            <td>{i['issue_type'].upper()}</td>
            <td>{i['facility_name']}</td>
            <td>{i['period']}</td>
            <td>{element}</td>
            <td>{value}</td>
            <td>{expected}</td>
            <td>{status_cell}</td>
            <td>{i['cascade_level']}</td>
            <td style="font-size:0.85em;color:#555">{i['resolution_notes'] or ''}</td>
            <td>{resend_btn}</td>
          </tr>""")

    table = '\n'.join(rows) if rows else '<tr><td colspan="11">No issues yet.</td></tr>'

    html = f"""<!DOCTYPE html>
<html><head>
  <title>AHEAD DQ Issue Log</title>
  <meta charset="utf-8">
  <meta http-equiv="refresh" content="10">
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
    .resend-btn {{ background: #ecf0f1; border: 1px solid #bdc3c7; border-radius: 4px;
                   padding: 3px 8px; font-size: .8rem; cursor: pointer; color: #555; }}
    .resend-btn:hover {{ background: #d5d8dc; }}
  </style>
</head><body>
  <h1>AHEAD DQ Issue Log</h1>
  <p>Auto-refreshes every 10 seconds. Status updates in real time as contacts respond.</p>
  <table>
    <thead>
      <tr>
        <th>Ref ID</th><th>Type</th><th>Facility</th><th>Period</th>
        <th>Element</th><th>Value</th><th>Expected</th>
        <th>Status</th><th>Level</th><th>Resolution</th><th></th>
      </tr>
    </thead>
    <tbody>{table}</tbody>
  </table>
</body></html>"""

    return Response(html, mimetype='text/html')


# ── Main ──────────────────────────────────────────────────────────────────────

def _start_ngrok(port=5001):
    """
    Start an ngrok tunnel so Twilio can reach the local webhook.
    Uses the ngrok binary (~/bin/ngrok or PATH); queries the local
    ngrok API to retrieve and print the public URL.
    """
    import subprocess, time, urllib.request as _ur, json as _json

    # Find the ngrok binary (prefer ~/bin/ngrok installed by setup)
    ngrok_bin = str(pathlib.Path.home() / 'bin' / 'ngrok')
    if not pathlib.Path(ngrok_bin).exists():
        ngrok_bin = 'ngrok'

    token = os.environ.get('NGROK_AUTHTOKEN', '')
    if token:
        subprocess.run([ngrok_bin, 'config', 'add-authtoken', token],
                       capture_output=True)

    proc = subprocess.Popen(
        [ngrok_bin, 'http', str(port)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

    time.sleep(2)  # wait for ngrok to initialise

    try:
        with _ur.urlopen('http://localhost:4040/api/tunnels', timeout=5) as r:
            tunnels = _json.loads(r.read()).get('tunnels', [])
        url = next((t['public_url'] for t in tunnels if t.get('proto') == 'https'), None)
        if url:
            print(f'[NGROK] public URL: {url}')
            print(f'[NGROK] *** set Twilio webhook → {url}/webhook/sms ***')
        else:
            print('[NGROK] tunnel started but could not retrieve URL — check http://localhost:4040')
    except Exception as e:
        print(f'[NGROK] could not query tunnel URL: {e}')

    return proc


if __name__ == '__main__':
    _startup()
    _sched  = _start_scheduler()
    _ngrok  = _start_ngrok()

    dhis2_base = os.environ.get('DHIS2_BASE_URL', 'http://localhost:8080/api')
    dhis2_url  = dhis2_base.replace('/api', '')
    print()
    print('  ┌──────────────────────────────────────────────────────────┐')
    print(f'  │  DHIS2               →  {dhis2_url}')
    print(f'  │  Issue log           →  http://localhost:5001/issues')
    print(f'  │  Health check        →  http://localhost:5001/api/health')
    print('  └──────────────────────────────────────────────────────────┘')
    print()

    try:
        app.run(host='0.0.0.0', port=5001, debug=False, use_reloader=False)
    finally:
        _sched.shutdown()
        if _ngrok:
            _ngrok.terminate()
