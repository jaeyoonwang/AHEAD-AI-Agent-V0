#!/usr/bin/env python3
"""
Conversation state machine for the AHEAD AI agent.

Entry points:
  notify_issue(ref_id)            — send the initial DQ alert SMS for a new issue
  handle_inbound(phone, text)     — process a reply from a contact; returns reply text
  escalate_due_issues()           — called every 30 min; escalates issues past their deadline
"""

import os, sys, pathlib, json
_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config as cfg
import dhis2_client as dc
from db import get_conn, get_active_conversation, get_contact_for_escalation
from sms import (send_sms, build_outlier_message, build_dtp_message,
                 build_missing_message, build_followup_prompt,
                 build_confirmation, build_escalation_notice)

_ai = None


def _get_ai():
    global _ai
    if _ai is None:
        import anthropic
        _ai = anthropic.Anthropic(api_key=os.environ.get('CLAUDE_API_KEY', ''))
    return _ai


# ── Option count per issue type ───────────────────────────────────────────────

_OPTION_COUNTS = {'outlier': 6, 'dtp': 5, 'missing': 4}


# ── Claude: parse which numbered option the user selected ────────────────────

def _parse_option(text, issue_type):
    """
    Return the integer option the user selected, or None if unclear.
    Uses Claude with a digit fallback for clean numeric replies.
    """
    stripped = text.strip()

    # Fast path: single digit reply
    if stripped.isdigit():
        n = int(stripped)
        return n if 1 <= n <= _OPTION_COUNTS.get(issue_type, 6) else None

    n_opts = _OPTION_COUNTS.get(issue_type, 6)
    prompt = (
        f'A user received an SMS DQ alert with {n_opts} numbered options. '
        f'They replied: "{stripped}"\n\n'
        f'Which option (1–{n_opts}) did they select? '
        f'Reply with JSON only, e.g. {{"option": 2}} or {{"option": null}} if unclear.'
    )
    try:
        msg = _get_ai().messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=30,
            messages=[{'role': 'user', 'content': prompt}]
        )
        data = json.loads(msg.content[0].text.strip())
        opt  = data.get('option')
        return int(opt) if opt and 1 <= int(opt) <= n_opts else None
    except Exception as e:
        print(f'[SM] option parse error: {e}')
        return None


# ── Claude: extract follow-up value ──────────────────────────────────────────

def _parse_followup_value(text, issue_type, selected_option):
    """
    Extract a numeric correction or date string from the user's follow-up reply.
    Returns the value as a string, or None if extraction fails.
    """
    stripped = text.strip()

    # Fast path: plain number
    if stripped.replace('.', '', 1).isdigit():
        return stripped

    if issue_type == 'missing' and selected_option == 1:
        prompt = (
            f'A user replied with an expected submission date: "{stripped}"\n'
            f'Extract the date string. Reply JSON only: {{"value": "<date or null>"}}'
        )
    else:
        prompt = (
            f'A user is providing a corrected numeric value. They said: "{stripped}"\n'
            f'Extract the number. Reply JSON only: {{"value": <number or null>}}'
        )
    try:
        msg = _get_ai().messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=30,
            messages=[{'role': 'user', 'content': prompt}]
        )
        data = json.loads(msg.content[0].text.strip())
        val  = data.get('value')
        return str(val) if val is not None else None
    except Exception as e:
        print(f'[SM] followup parse error: {e}')
        return None


# ── Resolution logic ──────────────────────────────────────────────────────────

_ACTION_NOTES = {
    'outlier': {
        1: 'Value confirmed correct. No action taken.',
        2: 'Data entry error noted. Please correct in DHIS2.',
        3: 'Stock/supply issue recorded.',
        5: 'Campaign doses recorded.',
        6: 'Reason recorded.',
    },
    'dtp': {
        1: 'Values confirmed correct. No action taken.',
        2: 'Catch-up campaign recorded.',
        3: 'Data entry error noted. Please correct in DHIS2.',
        5: 'Reason recorded.',
    },
    'missing': {
        2: 'Data loss recorded.',
        3: 'Connectivity issue recorded.',
        4: 'Reason recorded.',
    },
}


def _write_back_correction(issue, value):
    """
    Write a corrected value back to DHIS2 and return an action note string.
    outlier option 4 → corrects the flagged antigen
    dtp     option 4 → corrects Penta3
    """
    de_map = cfg.DATA_ELEMENTS
    coc    = cfg.CATEGORY_OPTION_COMBOS.get('under_1', '')

    de_uid = (de_map.get(issue['data_element']) if issue['issue_type'] == 'outlier'
              else de_map.get('Penta3'))
    if not de_uid:
        return f'Correction noted ({value}). Manual update may be needed.'

    try:
        dc.post_data_value(
            de_uid, issue['facility_uid'], issue['period'],
            coc, value,
            comment=f'Corrected via AHEAD DQ [{issue["ref_id"]}]'
        )
        return f'Value corrected to {value} in DHIS2.'
    except Exception as e:
        print(f'[SM] write-back error: {e}')
        return f'Correction noted ({value}). Manual update may be needed.'


def _build_issue_message(issue):
    """Build the outbound SMS body for the initial alert of an issue."""
    t = issue['issue_type']
    if t == 'outlier':
        return build_outlier_message(
            issue['ref_id'], issue['facility_name'], issue['period'],
            issue['data_element'], issue['flagged_value'],
            issue['expected_low'], issue['expected_high']
        )
    if t == 'dtp':
        # expected_low holds Penta1 (stored by dq_engine for display)
        return build_dtp_message(
            issue['ref_id'], issue['facility_name'], issue['period'],
            issue['expected_low'], issue['flagged_value']   # p1, p3
        )
    if t == 'missing':
        return build_missing_message(
            issue['ref_id'], issue['facility_name'], issue['period']
        )
    return None


def _resolve(conn, conv_id, ref_id, status, action_note):
    """Update issue status and close the conversation."""
    conn.execute(
        "UPDATE issues SET status=?, resolution_notes=?, resolved_at=CURRENT_TIMESTAMP WHERE ref_id=?",
        (status, action_note, ref_id)
    )
    conn.execute(
        "UPDATE conversations SET state='closed', updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (conv_id,)
    )


# ── Public: notify a new issue ────────────────────────────────────────────────

def notify_issue(ref_id):
    """
    Send the initial DQ alert SMS for a newly created issue.
    Called by dq_engine after each new issue is inserted.
    """
    with get_conn() as conn:
        issue = conn.execute('SELECT * FROM issues WHERE ref_id=?', (ref_id,)).fetchone()
        if not issue:
            return

        contact = get_contact_for_escalation(conn, issue['facility_uid'], 'facility')
        if not contact or not contact['phone']:
            print(f'[SM] no phone contact for {ref_id}')
            return

        body = _build_issue_message(issue)
        if not body:
            return

        send_sms(contact['phone'], body)

        conn.execute(
            'INSERT INTO conversations (issue_ref_id, phone) VALUES (?, ?)',
            (ref_id, contact['phone'])
        )
        conn.execute(
            'UPDATE issues SET notified_at=CURRENT_TIMESTAMP, last_retry_at=CURRENT_TIMESTAMP WHERE ref_id=?',
            (ref_id,)
        )
        print(f'[SM] notified {contact["phone"][:7]}*** → {ref_id}')


# ── Public: handle inbound SMS ────────────────────────────────────────────────

def handle_inbound(from_phone, text):
    """
    Process an inbound SMS reply. Returns the reply text to send back,
    or None if the sender has no active conversation.
    """
    with get_conn() as conn:
        conv = get_active_conversation(conn, from_phone)
        if not conv:
            return None  # no active issue — silently ignore

        issue = conn.execute(
            'SELECT * FROM issues WHERE ref_id=?', (conv['issue_ref_id'],)
        ).fetchone()
        if not issue:
            return None

        ref_id = issue['ref_id']
        body   = text.strip()
        state  = conv['state']

        # ── awaiting_option ──────────────────────────────────────────────────
        if state == 'awaiting_option':

            # Special case: SUBMIT keyword for missing reports
            if issue['issue_type'] == 'missing' and body.upper() == 'SUBMIT':
                _resolve(conn, conv['id'], ref_id, 'resolved', 'Submission acknowledged.')
                return build_confirmation(ref_id, 'Submission acknowledged.')

            option = _parse_option(body, issue['issue_type'])
            if option is None:
                n = _OPTION_COUNTS.get(issue['issue_type'], 6)
                return f'[{ref_id}] Please reply with a number 1–{n}.'

            followup = build_followup_prompt(issue['issue_type'], option)
            if followup:
                conn.execute(
                    "UPDATE conversations SET state='awaiting_followup', "
                    "selected_option=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (option, conv['id'])
                )
                return followup

            # No follow-up needed — resolve now
            action = _ACTION_NOTES.get(issue['issue_type'], {}).get(option, 'Response recorded.')
            status = 'ignored' if option == 1 else 'resolved'
            _resolve(conn, conv['id'], ref_id, status, action)
            return build_confirmation(ref_id, action)

        # ── awaiting_followup ────────────────────────────────────────────────
        elif state == 'awaiting_followup':
            selected = conv['selected_option']
            value    = _parse_followup_value(body, issue['issue_type'], selected)

            if value is None:
                return f'[{ref_id}] Please reply with a numeric value.'

            conn.execute(
                'UPDATE conversations SET followup_value=?, updated_at=CURRENT_TIMESTAMP WHERE id=?',
                (value, conv['id'])
            )

            if issue['issue_type'] in ('outlier', 'dtp') and selected == 4:
                action = _write_back_correction(issue, value)
            elif issue['issue_type'] == 'missing' and selected == 1:
                action = f'Expected submission date: {value}.'
            else:
                action = f'Value recorded: {value}.'

            _resolve(conn, conv['id'], ref_id, 'resolved', action)
            return build_confirmation(ref_id, action)

    return None


# ── Public: escalation timer ──────────────────────────────────────────────────

_CASCADE_ORDER = ['facility', 'woreda', 'zone', 'region']


def escalate_due_issues():
    """
    Called every 30 minutes by APScheduler. Escalates open issues where the
    current cascade level has been waiting longer than its configured deadline.

    Escalation timing (from config.py):
      facility → woreda : RETRY_INTERVAL_HOURS × MAX_RETRIES
      woreda   → zone   : ESCALATION_DAYS['woreda'] days from first notification
      zone     → region : ESCALATION_DAYS['zone']   days
      region   → (national monthly digest, no further escalation)
    """
    from datetime import datetime, timedelta

    now   = datetime.utcnow()
    retry = timedelta(hours=cfg.RETRY_INTERVAL_HOURS)

    with get_conn() as conn:
        open_issues = conn.execute(
            "SELECT * FROM issues WHERE status='open'"
        ).fetchall()

        for issue in open_issues:
            ref_id = issue['ref_id']
            level  = issue['cascade_level']
            retries = issue['retry_count']

            if not issue['notified_at']:
                continue

            notified_at = datetime.fromisoformat(issue['notified_at'])

            # Retry at facility level before escalating to woreda
            if level == 'facility' and retries < cfg.MAX_RETRIES:
                last_retry = datetime.fromisoformat(issue['last_retry_at']) if issue['last_retry_at'] else notified_at
                if now - last_retry >= retry:
                    _send_retry(conn, issue)
                continue

            # Escalate once retries are exhausted / deadline passed
            lvl_idx = _CASCADE_ORDER.index(level) if level in _CASCADE_ORDER else -1
            if lvl_idx < 0 or lvl_idx >= len(_CASCADE_ORDER) - 1:
                continue  # already at region or unknown level

            esc_days_key  = level  # 'facility'→'woreda' uses key 'woreda' etc.
            days_threshold = cfg.ESCALATION_DAYS.get(
                _CASCADE_ORDER[lvl_idx + 1], 999
            )
            if (now - notified_at).days >= days_threshold:
                _escalate(conn, issue, _CASCADE_ORDER[lvl_idx + 1])


def _send_retry(conn, issue):
    """Re-send the original alert (retry before escalating)."""
    contact = get_contact_for_escalation(conn, issue['facility_uid'], issue['cascade_level'])
    if not contact or not contact['phone']:
        return

    body = _build_issue_message(issue)
    if body:
        send_sms(contact['phone'], body)
        conn.execute(
            'UPDATE issues SET retry_count=retry_count+1, last_retry_at=CURRENT_TIMESTAMP WHERE ref_id=?',
            (issue['ref_id'],)
        )
        print(f'[SM] retry sent for {issue["ref_id"]} (count={issue["retry_count"]+1})')


def _escalate(conn, issue, new_level):
    """Escalate an issue to the next cascade level."""
    contact = get_contact_for_escalation(conn, issue['facility_uid'], new_level)
    if not contact or not contact['phone']:
        print(f'[SM] no {new_level} contact for escalation of {issue["ref_id"]}')
        return

    body = build_escalation_notice(
        issue['ref_id'], issue['facility_name'], issue['period'],
        issue['issue_type'], new_level
    )
    send_sms(contact['phone'], body)

    # Open a fresh conversation at the new level
    conn.execute(
        "UPDATE conversations SET state='closed', updated_at=CURRENT_TIMESTAMP "
        "WHERE issue_ref_id=? AND state != 'closed'",
        (issue['ref_id'],)
    )
    conn.execute(
        'INSERT INTO conversations (issue_ref_id, phone) VALUES (?, ?)',
        (issue['ref_id'], contact['phone'])
    )
    conn.execute(
        "UPDATE issues SET cascade_level=?, status='open', notified_at=CURRENT_TIMESTAMP, "
        "last_retry_at=CURRENT_TIMESTAMP, retry_count=0 WHERE ref_id=?",
        (new_level, issue['ref_id'])
    )
    print(f'[SM] escalated {issue["ref_id"]} → {new_level}')
