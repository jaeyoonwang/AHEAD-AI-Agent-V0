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

ACCOUNT_SID  = os.environ.get('TWILIO_ACCOUNT_SID', '')
AUTH_TOKEN   = os.environ.get('TWILIO_AUTH_TOKEN', '')
FROM_PHONE   = os.environ.get('TWILIO_PHONE', '')

# WhatsApp sandbox mode — set TWILIO_WHATSAPP=true in .env to route via WhatsApp.
# Sandbox sender is always +14155238886; recipients must opt in at wa.me/14155238886.
_WHATSAPP    = os.environ.get('TWILIO_WHATSAPP', '').lower() == 'true'
_WA_SANDBOX  = 'whatsapp:+14155238886'

_client = None


def _get_client():
    global _client
    if _client is None:
        from twilio.rest import Client
        _client = Client(ACCOUNT_SID, AUTH_TOKEN)
    return _client


def send_sms(to_phone, body):
    """Send an outbound message (SMS or WhatsApp depending on TWILIO_WHATSAPP env var)."""
    if _WHATSAPP:
        from_addr = _WA_SANDBOX
        to_addr   = f'whatsapp:{to_phone}'
    else:
        from_addr = FROM_PHONE
        to_addr   = to_phone
    msg = _get_client().messages.create(body=body, from_=from_addr, to=to_addr)
    channel = 'WA' if _WHATSAPP else 'SMS'
    print(f'[{channel}] → {to_phone[:7]}*** | {len(body)} chars | SID={msg.sid}')
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
    """
    6-option outlier alert matching the AHEAD Excel dropdown schema (section 2.2).

    Options:
      1. Replace with 6-month average  (agent auto-computes, asks for confirmation)
      2. Keep as-is                    (no data change)
      3. Set to zero                   (agent writes 0)
      4. Replace with specific value   (user provides the number)
      5. At health facility doses only (noted, manual adjustment by HQ)
      6. Outreach doses only           (noted, manual adjustment by HQ)
    """
    if expected_low is not None and expected_high is not None:
        exp = f'{max(0, int(expected_low))}–{int(expected_high)}'
    else:
        exp = 'N/A'
    return (
        f'AHEAD DQ Alert [{ref_id}]\n'
        f'{facility_name} — {period_label(period)}\n'
        f'{antigen}: {int(value)} doses (expected {exp})\n'
        f'\n'
        f'Reply with option number:\n'
        f'1. Replace with 6-month average\n'
        f'2. Keep as-is (no action)\n'
        f'3. Set to zero\n'
        f'4. Replace with specific value\n'
        f'5. At health facility doses only\n'
        f'6. Outreach doses only'
    )


def build_dtp_message(ref_id, facility_name, period, penta1, penta3):
    """
    5-option DTP1/DTP3 consistency alert matching AHEAD Excel dropdown schema (section 2.4).

    Options:
      1. Keep as-is              (no data change)
      2. Use DTP1 value for both (sets DTP3 = DTP1; agent auto-applies)
      3. Use DTP3 value for both (sets DTP1 = DTP3; agent auto-applies)
      4. Replace with specific value (user provides the corrected value)
      5. Other                   (noted, no automatic change)
    """
    diff_pct = round(abs((penta3 - penta1) / penta1) * 100) if penta1 else 0
    direction = 'DTP3 > DTP1' if penta3 > penta1 else 'DTP1 > DTP3'
    return (
        f'AHEAD DQ Alert [{ref_id}]\n'
        f'{facility_name} — {period_label(period)}\n'
        f'DTP1={int(penta1)}, DTP3={int(penta3)} ({direction}, gap: {diff_pct}%)\n'
        f'\n'
        f'Reply with option number:\n'
        f'1. Keep as-is (no action)\n'
        f'2. Use DTP1 value for both\n'
        f'3. Use DTP3 value for both\n'
        f'4. Replace with specific value\n'
        f'5. Other reason'
    )


def build_missing_message(ref_id, facility_name, period):
    """
    SUBMIT keyword + 4-option missing report alert (section 2.3).

    Recovery first — the primary goal is to get the report submitted.
    Cleaning options (average/zero/specific) apply only if recovery fails.

    Options:
      SUBMIT  Already submitted — agent acknowledges
      1.      Will submit by [date] (recovery)
      2.      Data cannot be recovered — HQ will impute (6-month average)
      3.      Facility closed / no service that month (agent sets to zero)
      4.      Other
    """
    return (
        f'AHEAD DQ Alert [{ref_id}]\n'
        f'{facility_name} — {period_label(period)}\n'
        f'Monthly EPI report not received.\n'
        f'\n'
        f'Reply SUBMIT if already submitted, or:\n'
        f'1. Will submit by [date]\n'
        f'2. Data cannot be recovered\n'
        f'3. Facility closed / no service that month\n'
        f'4. Other reason'
    )


def build_followup_prompt(issue_type, selected_option):
    """
    Prompt sent when the selected option requires the user to provide a value.
    Returns None if the option resolves immediately or is auto-computed.
    """
    if issue_type == 'outlier' and selected_option == 4:
        return 'Please reply with the correct value (numbers only, e.g. 97).'
    if issue_type == 'dtp' and selected_option == 4:
        return 'Please reply with the correct value (numbers only).'
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
