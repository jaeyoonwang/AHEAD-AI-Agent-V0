#!/usr/bin/env python3
"""
SMS layer: Twilio outbound client + numbered message templates.

Templates follow the AHEAD Excel dropdown schema:
  outlier  → 6 options
  dtp      → 5 options
  missing  → SUBMIT keyword + 4 numbered options

Claude (in state_machine.py) handles parsing inbound replies.
This module only knows how to build and send messages.
"""

import os, pathlib

def _load_env():
    p = pathlib.Path(__file__).resolve().parent
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

ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID', '')
AUTH_TOKEN  = os.environ.get('TWILIO_AUTH_TOKEN', '')
FROM_PHONE  = os.environ.get('TWILIO_PHONE', '')

_client = None


def _get_client():
    global _client
    if _client is None:
        from twilio.rest import Client
        _client = Client(ACCOUNT_SID, AUTH_TOKEN)
    return _client


def send_sms(to_phone, body):
    """Send an outbound SMS. Returns the Twilio message SID."""
    msg = _get_client().messages.create(body=body, from_=FROM_PHONE, to=to_phone)
    print(f'[SMS] → {to_phone[:7]}*** | {len(body)} chars | SID={msg.sid}')
    return msg.sid


# ── Display helpers ───────────────────────────────────────────────────────────

_MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']


def period_label(period_str):
    """'202606' → 'Jun 2026'"""
    try:
        y, m = int(period_str[:4]), int(period_str[4:6])
        return f'{_MONTHS[m-1]} {y}'
    except (ValueError, IndexError):
        return period_str


# ── Outbound templates ────────────────────────────────────────────────────────

def build_outlier_message(ref_id, facility_name, period, antigen,
                          value, expected_low, expected_high):
    """6-option outlier alert (AHEAD Excel dropdown schema)."""
    if expected_low is not None and expected_high is not None:
        exp = f'{int(expected_low)}–{int(expected_high)}'
    else:
        exp = 'N/A'
    return (
        f'AHEAD DQ Alert [{ref_id}]\n'
        f'{facility_name} — {period_label(period)}\n'
        f'{antigen}: {int(value)} doses (expected {exp})\n'
        f'\n'
        f'Reply with option number:\n'
        f'1. Confirmed correct\n'
        f'2. Data entry error — I will correct in DHIS2\n'
        f'3. Stock/supply issue\n'
        f'4. Correct value is [reply with number]\n'
        f'5. Campaign doses included\n'
        f'6. Other reason'
    )


def build_dtp_message(ref_id, facility_name, period, penta1, penta3):
    """5-option DTP consistency alert."""
    diff_pct = round(abs((penta3 - penta1) / penta1) * 100) if penta1 else 0
    return (
        f'AHEAD DQ Alert [{ref_id}]\n'
        f'{facility_name} — {period_label(period)}\n'
        f'DTP1={int(penta1)}, DTP3={int(penta3)} (gap: {diff_pct}%)\n'
        f'\n'
        f'Reply with option number:\n'
        f'1. Confirmed correct\n'
        f'2. Catch-up campaign included\n'
        f'3. Data entry error — I will correct in DHIS2\n'
        f'4. Correct DTP3 value is [reply with number]\n'
        f'5. Other reason'
    )


def build_missing_message(ref_id, facility_name, period):
    """SUBMIT keyword + 4-option missing report alert."""
    return (
        f'AHEAD DQ Alert [{ref_id}]\n'
        f'{facility_name} — {period_label(period)}\n'
        f'Monthly EPI report not received.\n'
        f'\n'
        f'Reply SUBMIT if already submitted, or:\n'
        f'1. Will submit by [date]\n'
        f'2. Data lost or damaged\n'
        f'3. No internet access\n'
        f'4. Other reason'
    )


def build_followup_prompt(issue_type, selected_option):
    """
    Prompt sent when the selected option requires a follow-up value.
    Returns None if no follow-up is needed for this option.
    """
    if issue_type == 'outlier' and selected_option == 4:
        return 'Please reply with the correct value (numbers only, e.g. 97).'
    if issue_type == 'dtp' and selected_option == 4:
        return 'Please reply with the correct DTP3 value (numbers only).'
    if issue_type == 'missing' and selected_option == 1:
        return 'Please reply with the expected submission date (e.g. 15 Jun).'
    return None


def build_confirmation(ref_id, action_note):
    """Closing message sent after an issue is resolved or acknowledged."""
    return f'[{ref_id}] Noted. {action_note} Thank you.'


def build_escalation_notice(ref_id, facility_name, period, issue_type, to_level):
    """Message sent to the next-level contact when escalating an unresolved issue."""
    labels = {
        'outlier': 'outlier value',
        'dtp':     'DTP inconsistency',
        'missing': 'missing report',
    }
    return (
        f'AHEAD DQ Escalation [{ref_id}]\n'
        f'{facility_name} — {period_label(period)}\n'
        f'Unresolved {labels.get(issue_type, issue_type)} escalated to {to_level} level.\n'
        f'Please follow up with the facility.'
    )
