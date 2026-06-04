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
                 build_confirmation, build_escalation_notice,
                 period_label, antigen_label)

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

# Immediate-resolution options (no follow-up, no write-back needed).
# Option numbers map to the AHEAD Excel dropdown schema from the reference guide.
_ACTION_NOTES = {
    'outlier': {
        2: 'Confirmed correct. No data change.',
        5: 'At-facility doses only. Noted for HQ manual adjustment.',
        6: 'Outreach doses only. Noted for HQ manual adjustment.',
    },
    'dtp': {
        1: 'Confirmed correct. No data change.',
        5: 'Reason recorded. No automatic data change.',
    },
    'missing': {
        2: 'Data loss recorded. Flagged for HQ imputation (6-month average).',
        4: 'Reason recorded.',
    },
}

# Options that go directly from option selection to confirmation (auto-computed value,
# no user input needed). Handled in _compute_auto_action().
_AUTO_CONFIRM_OPTIONS = {
    ('outlier', 1),   # replace with 6-month average
    ('outlier', 3),   # set to zero
    ('dtp',     2),   # use DTP1 value for both → set Penta3 = Penta1
    ('dtp',     3),   # use DTP3 value for both → set Penta1 = Penta3
    ('missing', 3),   # facility closed → set all vaccines to zero (recorded, manual HQ step)
}

# Options that need a user-provided follow-up value before confirmation.
_NEEDS_FOLLOWUP = {
    ('outlier', 4),   # replace with specific value
    ('dtp',     4),   # replace with specific value
    ('missing', 1),   # will submit by [date]
}


def _compute_auto_action(issue, option):
    """
    For options that can be auto-computed without user input, compute the target
    value and return (value_str, description). Returns None if computation fails.
    """
    de_map = cfg.DATA_ELEMENTS
    coc    = cfg.CATEGORY_OPTION_COMBOS.get('under_1', '')
    t      = issue['issue_type']

    if t == 'outlier' and option == 1:
        # Replace with 6-month average (surrounding periods)
        de_uid = de_map.get(issue['data_element'])
        if not de_uid:
            return None
        avg = dc.compute_surrounding_average(
            cfg.ROUTINE_DATASET_UID, de_uid,
            issue['facility_uid'], issue['period'], coc
        )
        if avg is None:
            return None
        return str(avg), f'Replace with 6-month average ({avg})'

    if t == 'outlier' and option == 3:
        return '0', 'Set to zero'

    if t == 'dtp' and option == 2:
        # Use DTP1 for both: set Penta3 = Penta1 value (stored in expected_low)
        p1_val = issue['expected_low']
        if p1_val is None:
            return None
        val = str(int(p1_val))
        return val, f'Set DTP3 to match DTP1 ({val})'

    if t == 'dtp' and option == 3:
        # Use DTP3 for both: set Penta1 = Penta3 value (stored in flagged_value)
        p3_val = issue['flagged_value']
        if p3_val is None:
            return None
        val = str(int(p3_val))
        return val, f'Set DTP1 to match DTP3 ({val})'

    if t == 'missing' and option == 3:
        # Facility closed — record only; HQ handles zero imputation across all vaccines
        return 'closed', 'Facility closed / no service that month'

    return None


def _build_confirmation_prompt(issue, value, selected_option):
    """
    Unified YES/NO confirmation prompt for every write-back option.

    All data corrections use the same format:
      [REF] Confirm change:
      {element} — {facility} ({period})
      {old} → {new}  [optional: (reason)]

      Reply YES to update DHIS2 or NO to choose again.

    Non-data confirmations (missing date/closure) use a shorter variant.
    """
    ref = issue['ref_id']
    fac = issue['facility_name']
    per = period_label(issue['period'])
    t   = issue['issue_type']

    def _i(v):
        """Format any value as a rounded integer string for display."""
        try:
            return str(int(round(float(v))))
        except (TypeError, ValueError):
            return str(v)

    def _change(element_label, old_val, new_val, note=None):
        line = f'{_i(old_val)} → {_i(new_val)}'
        if note:
            line += f' ({note})'
        return (
            f'[{ref}] Confirm change:\n'
            f'{element_label} — {fac} ({per})\n'
            f'{line}\n\n'
            f'Reply YES to update DHIS2 or NO to choose again.'
        )

    if t == 'outlier':
        el  = antigen_label(issue['data_element'])
        old = issue['flagged_value']
        if selected_option == 1:
            return _change(el, old, value, '6-month average')
        if selected_option == 3:
            return _change(el, old, 0, 'set to zero')
        if selected_option == 4:
            return _change(el, old, value)

    if t == 'dtp':
        p1_label = antigen_label('Penta1')
        p3_label = antigen_label('Penta3')
        if selected_option == 2:
            return _change(p3_label, issue['flagged_value'], value,
                           'use DTP1 value for both')
        if selected_option == 3:
            return _change(p1_label, issue['expected_low'], value,
                           'use DTP3 value for both')
        if selected_option == 4:
            return _change(p3_label, issue['flagged_value'], value)

    if t == 'missing':
        if selected_option == 1:
            return (
                f'[{ref}] Confirm:\n'
                f'Expected submission for {fac} ({per}): {value}\n\n'
                f'Reply YES to confirm or NO to re-enter.'
            )
        if selected_option == 3:
            return (
                f'[{ref}] Confirm:\n'
                f'Record facility closure for {fac} ({per}).\n'
                f'Flagged for HQ zero imputation.\n\n'
                f'Reply YES to confirm or NO to choose again.'
            )

    return f'[{ref}] Confirm value {value}? Reply YES or NO.'


def _execute_write_back(issue, selected_option, value):
    """
    Execute the confirmed write-back for options that modify DHIS2 data.
    Returns an action note string describing what was done.
    """
    de_map = cfg.DATA_ELEMENTS
    coc    = cfg.CATEGORY_OPTION_COMBOS.get('under_1', '')
    t      = issue['issue_type']
    ref    = issue['ref_id']

    def _write(de_uid, val, note):
        try:
            # Always write integer doses — DHIS2 rejects decimal values for
            # integer-typed data elements (causes silent 409 failure otherwise).
            int_val = str(int(round(float(val))))
            dc.post_data_value(
                de_uid, issue['facility_uid'], issue['period'],
                coc, int_val, comment=f'AHEAD DQ correction [{ref}]'
            )
            return note
        except Exception as e:
            print(f'[SM] write-back error: {e}')
            return f'Correction noted ({val}). Manual update required.'

    if t == 'outlier':
        de_uid = de_map.get(issue['data_element'])
        el     = antigen_label(issue['data_element'])
        if not de_uid:
            return f'Configuration error: unknown element {issue["data_element"]}.'
        if selected_option == 1:
            return _write(de_uid, value, f'{el} replaced with 6-month average ({value}) in DHIS2.')
        if selected_option == 3:
            return _write(de_uid, '0', f'{el} set to zero in DHIS2.')
        if selected_option == 4:
            return _write(de_uid, value, f'{el} corrected to {value} in DHIS2.')

    if t == 'dtp':
        p1_uid   = de_map.get('Penta1')
        p3_uid   = de_map.get('Penta3')
        p1_label = antigen_label('Penta1')
        p3_label = antigen_label('Penta3')
        if selected_option == 2:
            return _write(p3_uid, value, f'{p3_label} set to match {p1_label} ({value}) in DHIS2.')
        if selected_option == 3:
            return _write(p1_uid, value, f'{p1_label} set to match {p3_label} ({value}) in DHIS2.')
        if selected_option == 4:
            return _write(p3_uid, value, f'{p3_label} corrected to {value} in DHIS2.')

    if t == 'missing':
        if selected_option == 1:
            return f'Expected submission date recorded: {value}.'
        if selected_option == 3:
            return 'Facility closure confirmed. Flagged for HQ zero imputation.'

    return f'Value recorded: {value}.'


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


# ── Public helpers ───────────────────────────────────────────────────────────

def _get_contact_for_issue(conn, issue):
    """Return the contact for an issue's current cascade level (or None)."""
    return get_contact_for_escalation(conn, issue['facility_uid'], issue['cascade_level'])


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

    Conversation states:
      awaiting_option       user picks a numbered option
      awaiting_followup     user provides a value (dose count, date, etc.)
      awaiting_confirmation user confirms YES/NO before any DHIS2 write
      closed                done
    """
    with get_conn() as conn:
        conv = get_active_conversation(conn, from_phone)
        if not conv:
            return None

        issue = conn.execute(
            'SELECT * FROM issues WHERE ref_id=?', (conv['issue_ref_id'],)
        ).fetchone()
        if not issue:
            return None

        ref_id = issue['ref_id']
        body   = text.strip()
        state  = conv['state']

        # Mark issue as in-progress on first reply
        if issue['status'] == 'open':
            conn.execute(
                "UPDATE issues SET status='in_progress' WHERE ref_id=?", (ref_id,)
            )

        # ── awaiting_option ──────────────────────────────────────────────────
        if state == 'awaiting_option':

            # SUBMIT keyword for missing reports (recovery path)
            if issue['issue_type'] == 'missing' and body.upper() == 'SUBMIT':
                _resolve(conn, conv['id'], ref_id, 'resolved', 'Submission acknowledged.')
                return build_confirmation(ref_id, 'Submission acknowledged.')

            option = _parse_option(body, issue['issue_type'])
            if option is None:
                n = _OPTION_COUNTS.get(issue['issue_type'], 6)
                return f'[{ref_id}] Please reply with a number 1–{n}.'

            # Option needs user-provided value first
            if (issue['issue_type'], option) in _NEEDS_FOLLOWUP:
                followup = build_followup_prompt(issue['issue_type'], option)
                conn.execute(
                    "UPDATE conversations SET state='awaiting_followup', "
                    "selected_option=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (option, conv['id'])
                )
                return followup

            # Option can be auto-computed → go straight to confirmation
            if (issue['issue_type'], option) in _AUTO_CONFIRM_OPTIONS:
                result = _compute_auto_action(issue, option)
                if result is None:
                    return (f'[{ref_id}] Could not compute automatic correction '
                            f'(insufficient history). Please choose another option.')
                value, description = result
                conn.execute(
                    "UPDATE conversations SET state='awaiting_confirmation', "
                    "selected_option=?, followup_value=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (option, value, conv['id'])
                )
                return _build_confirmation_prompt(issue, value, option)

            # Immediate resolution — no write-back
            action = _ACTION_NOTES.get(issue['issue_type'], {}).get(option, 'Response recorded.')
            status = 'ignored' if option in (1, 2) and issue['issue_type'] != 'missing' else 'resolved'
            _resolve(conn, conv['id'], ref_id, status, action)
            return build_confirmation(ref_id, action)

        # ── awaiting_followup ────────────────────────────────────────────────
        elif state == 'awaiting_followup':
            selected = conv['selected_option']
            value    = _parse_followup_value(body, issue['issue_type'], selected)

            if value is None:
                return f'[{ref_id}] Please reply with a numeric value only.'

            conn.execute(
                'UPDATE conversations SET followup_value=?, updated_at=CURRENT_TIMESTAMP WHERE id=?',
                (value, conv['id'])
            )
            conn.execute(
                "UPDATE conversations SET state='awaiting_confirmation', "
                "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (conv['id'],)
            )
            return _build_confirmation_prompt(issue, value, selected)

        # ── awaiting_confirmation ────────────────────────────────────────────
        elif state == 'awaiting_confirmation':
            selected = conv['selected_option']
            value    = conv['followup_value']
            clean    = body.upper().strip()

            if clean in ('YES', 'Y', 'CONFIRM', 'OK'):
                action = _execute_write_back(issue, selected, value)
                _resolve(conn, conv['id'], ref_id, 'resolved', action)
                return build_confirmation(ref_id, action)

            elif clean in ('NO', 'N', 'CANCEL'):
                # Go back to option selection — re-send the original alert
                conn.execute(
                    "UPDATE conversations SET state='awaiting_option', selected_option=NULL, "
                    "followup_value=NULL, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (conv['id'],)
                )
                return _build_issue_message(issue)

            else:
                return f'[{ref_id}] Please reply YES to confirm or NO to choose again.'

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
