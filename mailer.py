"""mailer.py — OTP email delivery for Agentic AI DSL Colab.

Uses Python's built-in ``smtplib`` (no external mail package required), so it
works out of the box once MAIL_USERNAME + MAIL_PASSWORD are configured.

SECURITY: OTPs are ONLY delivered by email. The plaintext OTP is NEVER returned
to any caller, stored in the session, included in an HTTP response, or written
to any log the user can see. Only a SHA-256 hash is ever persisted.

If mail is not configured, the auth flow refuses to proceed — it never falls
back to displaying the OTP on screen.
"""
from __future__ import annotations

import hashlib
import os
import smtplib
import ssl
import sys
from email.message import EmailMessage
from typing import Optional

# Module-level config, populated by init_mail()
_cfg = {
    "configured": False,
    "server": "smtp.gmail.com",
    "port": 587,
    "use_tls": True,
    "use_ssl": False,
    "username": "",
    "password": "",
    "sender": "",
    "timeout": 20,
}


# ---------------------------------------------------------------------------
#  Initialisation
# ---------------------------------------------------------------------------
def init_mail(app=None) -> bool:
    """Read mail settings from the environment. Returns True when configured.

    Prints a clear status banner so misconfiguration is obvious at startup.
    The *app* argument is accepted for compatibility but is not required.
    """
    username = os.getenv("MAIL_USERNAME", "").strip()
    # Gmail shows App Passwords grouped as "abcd efgh ijkl mnop" — the real
    # value has NO spaces. Strip ALL whitespace so either form works.
    password = "".join(os.getenv("MAIL_PASSWORD", "").split())

    if not username or not password:
        _cfg["configured"] = False
        print("=" * 64)
        print(" [MAIL] DISABLED — MAIL_USERNAME / MAIL_PASSWORD not set.")
        print(" OTP email (registration, 2FA, password reset) will NOT work.")
        print(" Add these to your .env file, then restart:")
        print("     MAIL_USERNAME=youraddress@gmail.com")
        print("     MAIL_PASSWORD=your16charapppassword")
        print("=" * 64)
        return False

    _cfg.update({
        "configured": True,
        "server":   os.getenv("MAIL_SERVER", "smtp.gmail.com"),
        "port":     int(os.getenv("MAIL_PORT", "587")),
        "use_tls":  os.getenv("MAIL_USE_TLS", "true").lower() != "false",
        "use_ssl":  os.getenv("MAIL_USE_SSL", "false").lower() == "true",
        "username": username,
        "password": password,
        "sender":   os.getenv("MAIL_DEFAULT_SENDER", username),
        "timeout":  int(os.getenv("MAIL_TIMEOUT", "20")),
    })
    print("=" * 64)
    print(f" [MAIL] ENABLED — OTP email via {_cfg['server']}:{_cfg['port']} "
          f"({'SSL' if _cfg['use_ssl'] else 'STARTTLS' if _cfg['use_tls'] else 'plain'})")
    print(f"        Sender account: {username}")
    print("=" * 64)
    return True


def is_configured() -> bool:
    return _cfg["configured"]


# ---------------------------------------------------------------------------
#  OTP helpers
# ---------------------------------------------------------------------------
def generate_otp() -> str:
    """Cryptographically secure 6-digit OTP string."""
    import secrets
    return f"{secrets.randbelow(900000) + 100000}"


def hash_otp(otp: str) -> str:
    """SHA-256 hash of the OTP — only the hash is stored in the database."""
    return hashlib.sha256(otp.encode()).hexdigest()


def verify_otp_hash(otp: str, stored_hash: str) -> bool:
    return hashlib.compare_digest(hash_otp(otp), stored_hash)


# ---------------------------------------------------------------------------
#  Email composition
# ---------------------------------------------------------------------------
_SUBJECTS = {
    "register":        "Verify your email — Agentic AI DSL Colab",
    "2fa":             "Your two-factor login code — Agentic AI DSL Colab",
    "forgot_password": "Reset your password — Agentic AI DSL Colab",
}

_INTRO = {
    "register":        "Welcome! Use the code below to verify your email and finish creating your account.",
    "2fa":             "Use the code below to complete your sign-in.",
    "forgot_password": "Use the code below to reset your password.",
}

_FOOTER = {
    "register":        "If you did not sign up, you can ignore this email.",
    "2fa":             "If you did not attempt to sign in, change your password immediately.",
    "forgot_password": "If you did not request a password reset, you can ignore this email.",
}


def _build_message(to_email: str, otp: str, purpose: str) -> EmailMessage:
    subject = _SUBJECTS.get(purpose, "Your verification code — Agentic AI DSL Colab")
    intro = _INTRO.get(purpose, "Use the code below to continue.")
    footer = _FOOTER.get(purpose, "")

    text = (
        f"{intro}\n\n"
        f"    {otp}\n\n"
        f"This code expires in 5 minutes. Do not share it with anyone.\n\n"
        f"{footer}\n\n"
        f"— Agentic AI DSL Colab"
    )
    html = f"""\
<div style="font-family:Arial,Helvetica,sans-serif;max-width:460px;margin:auto;
            border:1px solid #e8eaed;border-radius:12px;padding:28px 32px;color:#202124">
  <h2 style="margin:0 0 4px;font-weight:600">Agentic AI DSL Colab</h2>
  <p style="color:#5f6368;margin:0 0 20px">{intro}</p>
  <div style="background:#f1f3f4;border-radius:10px;text-align:center;padding:18px 0;margin-bottom:18px">
    <span style="font-size:34px;font-weight:700;letter-spacing:10px;color:#1a73e8;
                 font-family:'Courier New',monospace">{otp}</span>
  </div>
  <p style="color:#5f6368;font-size:13px;margin:0 0 6px">
    This code expires in <strong>5 minutes</strong>. Do not share it with anyone.</p>
  <p style="color:#9aa0a6;font-size:12px;margin:16px 0 0">{footer}</p>
</div>"""

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = _cfg["sender"]
    msg["To"] = to_email
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    return msg


# ---------------------------------------------------------------------------
#  Sending — NEVER exposes OTP to the caller
# ---------------------------------------------------------------------------
_MAIL_NOT_CONFIGURED = (
    "Email is not configured on this server. Set MAIL_USERNAME and "
    "MAIL_PASSWORD (a Gmail App Password) in your .env file and restart."
)


def send_otp(to_email: str, otp: str, purpose: str) -> Optional[str]:
    """Send an OTP email. Returns None on success, an error string on failure.

    The *otp* is used only to compose the message body and is never returned
    or logged in plaintext anywhere the user can see.
    """
    if not _cfg["configured"]:
        _log(f"[MAIL NOT CONFIGURED] Cannot send OTP to {to_email} "
             f"(purpose={purpose}). Set MAIL_USERNAME + MAIL_PASSWORD.")
        return _MAIL_NOT_CONFIGURED

    msg = _build_message(to_email, otp, purpose)
    try:
        context = ssl.create_default_context()
        if _cfg["use_ssl"]:
            with smtplib.SMTP_SSL(_cfg["server"], _cfg["port"],
                                  context=context, timeout=_cfg["timeout"]) as s:
                s.login(_cfg["username"], _cfg["password"])
                s.send_message(msg)
        else:
            with smtplib.SMTP(_cfg["server"], _cfg["port"], timeout=_cfg["timeout"]) as s:
                s.ehlo()
                if _cfg["use_tls"]:
                    s.starttls(context=context)
                    s.ehlo()
                s.login(_cfg["username"], _cfg["password"])
                s.send_message(msg)
        _log(f"[MAIL] OTP sent to {to_email} (purpose={purpose})")
        return None

    except smtplib.SMTPAuthenticationError as exc:
        _log(f"[MAIL ERROR] Authentication failed for {to_email}: {exc}")
        _log("        → Gmail rejected the credentials. You MUST use a 16-char "
             "App Password (not your normal password), and 2-Step Verification "
             "must be ON. Create one at https://myaccount.google.com/apppasswords")
        return "Could not send the email: the mail account credentials were rejected."
    except (smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected, OSError) as exc:
        _log(f"[MAIL ERROR] Connection problem sending to {to_email}: {exc}")
        _log("        → Could not reach the SMTP server. Check MAIL_SERVER/MAIL_PORT "
             "and that outbound port 587 (or 465 for SSL) is not blocked.")
        return "Could not connect to the mail server. Please try again shortly."
    except Exception as exc:  # noqa: BLE001
        _log(f"[MAIL ERROR] Failed to send to {to_email}: {exc}")
        return "Failed to send the verification email. Please try again in a moment."


def send_test_email(to_email: str) -> Optional[str]:
    """Send a test message to verify configuration (used by scripts/admin)."""
    if not _cfg["configured"]:
        return _MAIL_NOT_CONFIGURED
    msg = EmailMessage()
    msg["Subject"] = "Test email — Agentic AI DSL Colab"
    msg["From"] = _cfg["sender"]
    msg["To"] = to_email
    msg.set_content("If you received this, your SMTP settings are working correctly.")
    saved = (_cfg["server"], _cfg["port"])
    try:
        context = ssl.create_default_context()
        if _cfg["use_ssl"]:
            with smtplib.SMTP_SSL(*saved, context=context, timeout=_cfg["timeout"]) as s:
                s.login(_cfg["username"], _cfg["password"]); s.send_message(msg)
        else:
            with smtplib.SMTP(*saved, timeout=_cfg["timeout"]) as s:
                s.ehlo()
                if _cfg["use_tls"]:
                    s.starttls(context=context); s.ehlo()
                s.login(_cfg["username"], _cfg["password"]); s.send_message(msg)
        return None
    except Exception as exc:  # noqa: BLE001
        return str(exc)


def _log(msg: str):
    """Write to stdout (server console only — never reaches the browser)."""
    print(msg, flush=True, file=sys.stdout)
