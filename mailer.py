"""mailer.py — OTP email delivery for Agentic AI DSL Colab.

Supports multiple delivery backends, chosen automatically from environment vars:

  1. Brevo   HTTP API  (BREVO_API_KEY)      — works on Render (port 443)
  2. SendGrid HTTP API (SENDGRID_API_KEY)   — works on Render (port 443)
  3. Resend  HTTP API  (RESEND_API_KEY)     — works on Render (port 443)
  4. SMTP              (MAIL_USERNAME+MAIL_PASSWORD) — for local/VM hosts

Many cloud hosts (including Render) BLOCK outbound SMTP ports (25/465/587),
so on those hosts you must use one of the HTTP API providers above.

SECURITY: OTPs are ONLY delivered by email. The plaintext OTP is NEVER returned
to any caller, stored in the session, included in an HTTP response, or written
to any log the user can see. Only a SHA-256 hash is ever persisted.
"""
from __future__ import annotations

import hashlib
import json
import os
import smtplib
import ssl
import sys
import urllib.error
import urllib.request
from email.message import EmailMessage
from typing import Optional

# Populated by init_mail()
_cfg = {
    "mode": None,        # "brevo" | "sendgrid" | "resend" | "smtp" | None
    "api_key": "",
    "from_email": "",
    "from_name": "Agentic AI DSL Colab",
    # SMTP-only
    "server": "smtp.gmail.com",
    "port": 587,
    "use_tls": True,
    "use_ssl": False,
    "username": "",
    "password": "",
    "timeout": 20,
}


# ---------------------------------------------------------------------------
#  Initialisation
# ---------------------------------------------------------------------------
def init_mail(app=None) -> bool:
    """Pick the email backend from env vars. Returns True when configured."""
    from_name = os.getenv("MAIL_FROM_NAME", "Agentic AI DSL Colab").strip()
    # The verified sender address (Brevo/SendGrid require a verified sender).
    from_email = (os.getenv("MAIL_FROM", "").strip()
                  or os.getenv("MAIL_USERNAME", "").strip())

    brevo = os.getenv("BREVO_API_KEY", "").strip()
    sendgrid = os.getenv("SENDGRID_API_KEY", "").strip()
    resend = os.getenv("RESEND_API_KEY", "").strip()
    smtp_user = os.getenv("MAIL_USERNAME", "").strip()
    smtp_pass = "".join(os.getenv("MAIL_PASSWORD", "").split())  # strip spaces

    _cfg["from_name"] = from_name or "Agentic AI DSL Colab"
    _cfg["from_email"] = from_email

    if brevo:
        _cfg.update({"mode": "brevo", "api_key": brevo})
        _banner("Brevo HTTP API", f"sender {from_email or '(set MAIL_FROM!)'}")
        return True
    if sendgrid:
        _cfg.update({"mode": "sendgrid", "api_key": sendgrid})
        _banner("SendGrid HTTP API", f"sender {from_email or '(set MAIL_FROM!)'}")
        return True
    if resend:
        _cfg.update({"mode": "resend", "api_key": resend})
        _banner("Resend HTTP API", f"sender {from_email or '(set MAIL_FROM!)'}")
        return True
    if smtp_user and smtp_pass:
        _cfg.update({
            "mode": "smtp",
            "username": smtp_user, "password": smtp_pass,
            "from_email": from_email or smtp_user,
            "server": os.getenv("MAIL_SERVER", "smtp.gmail.com"),
            "port": int(os.getenv("MAIL_PORT", "587")),
            "use_tls": os.getenv("MAIL_USE_TLS", "true").lower() != "false",
            "use_ssl": os.getenv("MAIL_USE_SSL", "false").lower() == "true",
            "timeout": int(os.getenv("MAIL_TIMEOUT", "20")),
        })
        _banner(f"SMTP {_cfg['server']}:{_cfg['port']}", f"sender {smtp_user}",
                warn=("Many cloud hosts block SMTP. If sending fails with "
                      "'Network is unreachable', use Brevo (BREVO_API_KEY) instead."))
        return True

    _cfg["mode"] = None
    print("=" * 64)
    print(" [MAIL] DISABLED — no email backend configured.")
    print(" OTP email (registration, 2FA, password reset) will NOT work.")
    print(" On Render (or any host that blocks SMTP), set:")
    print("     BREVO_API_KEY=...        (free at https://www.brevo.com)")
    print("     MAIL_FROM=your_verified_sender@example.com")
    print(" For local use you can instead set MAIL_USERNAME + MAIL_PASSWORD.")
    print("=" * 64)
    return False


def _banner(via: str, who: str, warn: str = ""):
    print("=" * 64)
    print(f" [MAIL] ENABLED — OTP email via {via}")
    print(f"        {who}")
    if warn:
        print(f"        NOTE: {warn}")
    print("=" * 64)


def is_configured() -> bool:
    return _cfg["mode"] is not None


# ---------------------------------------------------------------------------
#  OTP helpers
# ---------------------------------------------------------------------------
def generate_otp() -> str:
    import secrets
    return f"{secrets.randbelow(900000) + 100000}"


def hash_otp(otp: str) -> str:
    return hashlib.sha256(otp.encode()).hexdigest()


def verify_otp_hash(otp: str, stored_hash: str) -> bool:
    return hashlib.compare_digest(hash_otp(otp), stored_hash)


# ---------------------------------------------------------------------------
#  Message content
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


def _content(otp: str, purpose: str):
    subject = _SUBJECTS.get(purpose, "Your verification code — Agentic AI DSL Colab")
    intro = _INTRO.get(purpose, "Use the code below to continue.")
    footer = _FOOTER.get(purpose, "")
    text = (f"{intro}\n\n    {otp}\n\n"
            f"This code expires in 5 minutes. Do not share it with anyone.\n\n"
            f"{footer}\n\n— Agentic AI DSL Colab")
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
    return subject, text, html


# ---------------------------------------------------------------------------
#  Sending — dispatch to the configured backend
# ---------------------------------------------------------------------------
_NOT_CONFIGURED = ("Email is not configured on this server. Set BREVO_API_KEY "
                   "(or SENDGRID_API_KEY) and MAIL_FROM, then redeploy.")


def send_otp(to_email: str, otp: str, purpose: str) -> Optional[str]:
    """Send an OTP. Returns None on success, an error string on failure.
    The OTP is used only to build the email and is never returned or logged."""
    mode = _cfg["mode"]
    if mode is None:
        _log(f"[MAIL NOT CONFIGURED] Cannot send OTP to {to_email} ({purpose}).")
        return _NOT_CONFIGURED

    subject, text, html = _content(otp, purpose)
    try:
        if mode == "brevo":
            err = _send_brevo(to_email, subject, text, html)
        elif mode == "sendgrid":
            err = _send_sendgrid(to_email, subject, text, html)
        elif mode == "resend":
            err = _send_resend(to_email, subject, text, html)
        else:
            err = _send_smtp(to_email, subject, text, html)
    except Exception as exc:  # noqa: BLE001
        _log(f"[MAIL ERROR] Unexpected error sending to {to_email}: {exc}")
        return "Failed to send the verification email. Please try again."

    if err is None:
        _log(f"[MAIL] OTP sent to {to_email} via {mode} (purpose={purpose})")
    return err


# ---- HTTP providers (work on Render — use port 443) -----------------------
def _http_post(url: str, headers: dict, body: dict) -> Optional[str]:
    """POST JSON. Returns None on 2xx, else an error string (logged server-side)."""
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            if 200 <= resp.status < 300:
                return None
            _log(f"[MAIL ERROR] {url} returned HTTP {resp.status}")
            return "Email provider returned an error. Please try again."
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")[:300]
        _log(f"[MAIL ERROR] {url} HTTP {e.code}: {detail}")
        if e.code in (401, 403):
            return "Email provider rejected the API key. Check your configuration."
        return "Email provider returned an error. Please try again."
    except Exception as exc:  # noqa: BLE001
        _log(f"[MAIL ERROR] Could not reach {url}: {exc}")
        return "Could not reach the email service. Please try again shortly."


def _send_brevo(to_email, subject, text, html):
    if not _cfg["from_email"]:
        _log("[MAIL ERROR] MAIL_FROM not set (required for Brevo).")
        return "Email sender is not configured (MAIL_FROM)."
    return _http_post(
        "https://api.brevo.com/v3/smtp/email",
        {"api-key": _cfg["api_key"], "content-type": "application/json",
         "accept": "application/json"},
        {"sender": {"name": _cfg["from_name"], "email": _cfg["from_email"]},
         "to": [{"email": to_email}],
         "subject": subject, "textContent": text, "htmlContent": html},
    )


def _send_sendgrid(to_email, subject, text, html):
    if not _cfg["from_email"]:
        return "Email sender is not configured (MAIL_FROM)."
    return _http_post(
        "https://api.sendgrid.com/v3/mail/send",
        {"Authorization": f"Bearer {_cfg['api_key']}",
         "Content-Type": "application/json"},
        {"personalizations": [{"to": [{"email": to_email}]}],
         "from": {"email": _cfg["from_email"], "name": _cfg["from_name"]},
         "subject": subject,
         "content": [{"type": "text/plain", "value": text},
                     {"type": "text/html", "value": html}]},
    )


def _send_resend(to_email, subject, text, html):
    if not _cfg["from_email"]:
        return "Email sender is not configured (MAIL_FROM)."
    return _http_post(
        "https://api.resend.com/emails",
        {"Authorization": f"Bearer {_cfg['api_key']}",
         "Content-Type": "application/json", 
         "User-Agent": "agentic-colab/1.0"},
        {"from": f"{_cfg['from_name']} <{_cfg['from_email']}>",
         "to": [to_email], "subject": subject, "text": text, "html": html},
    )


# ---- SMTP (local / hosts that allow it) -----------------------------------
def _send_smtp(to_email, subject, text, html):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = _cfg["from_email"] or _cfg["username"]
    msg["To"] = to_email
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    try:
        context = ssl.create_default_context()
        if _cfg["use_ssl"]:
            with smtplib.SMTP_SSL(_cfg["server"], _cfg["port"],
                                  context=context, timeout=_cfg["timeout"]) as s:
                s.login(_cfg["username"], _cfg["password"]); s.send_message(msg)
        else:
            with smtplib.SMTP(_cfg["server"], _cfg["port"], timeout=_cfg["timeout"]) as s:
                s.ehlo()
                if _cfg["use_tls"]:
                    s.starttls(context=context); s.ehlo()
                s.login(_cfg["username"], _cfg["password"]); s.send_message(msg)
        return None
    except smtplib.SMTPAuthenticationError as exc:
        _log(f"[MAIL ERROR] SMTP auth failed: {exc}")
        return "Could not send the email: the mail account credentials were rejected."
    except (smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected, OSError) as exc:
        _log(f"[MAIL ERROR] SMTP connection problem: {exc}")
        _log("        → This host likely BLOCKS outbound SMTP (common on Render). "
             "Use Brevo (BREVO_API_KEY) over HTTP instead.")
        return "Could not connect to the mail server. (This host may block SMTP — use an email API.)"
    except Exception as exc:  # noqa: BLE001
        _log(f"[MAIL ERROR] SMTP send failed: {exc}")
        return "Failed to send the verification email. Please try again."


def _log(msg: str):
    """Write to stdout (server console only — never reaches the browser)."""
    print(msg, flush=True, file=sys.stdout)
