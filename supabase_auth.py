"""Supabase Auth helper for Agentic AI DSL Colab.

Only email/password Supabase Authentication is used here. No Resend, Brevo,
SendGrid, SMTP, or OTP mailer is required by this application.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Dict

_cfg = {"url": "", "anon_key": ""}


def _clean_url(value: str) -> str:
    value = (value or "").strip().strip('"').strip("'").rstrip("/")
    return value


def init_supabase() -> bool:
    _cfg["url"] = _clean_url(os.getenv("SUPABASE_URL", ""))
    _cfg["anon_key"] = (os.getenv("SUPABASE_ANON_KEY", "") or "").strip().strip('"').strip("'")
    print("=" * 64)
    if is_configured():
        print(" [AUTH] ENABLED — Supabase email/password authentication")
        print(f"        url {_cfg['url']}")
    else:
        print(" [AUTH] DISABLED — Supabase is not configured")
        print("        Set SUPABASE_URL and SUPABASE_ANON_KEY in Render")
    print("=" * 64)
    return is_configured()


def is_configured() -> bool:
    return bool(_cfg["url"] and _cfg["anon_key"])


def _headers() -> Dict[str, str]:
    return {
        "apikey": _cfg["anon_key"],
        "Authorization": f"Bearer {_cfg['anon_key']}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "agentic-colab/1.0",
    }


def _post(path: str, body: Dict) -> Dict:
    if not is_configured():
        raise RuntimeError("Supabase is not configured. Set SUPABASE_URL and SUPABASE_ANON_KEY in Render.")
    url = _cfg["url"] + path
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=_headers(), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", "ignore")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")
        try:
            payload = json.loads(detail)
            msg = payload.get("msg") or payload.get("message") or payload.get("error_description") or detail
        except Exception:
            msg = detail or f"HTTP {e.code}"
        raise RuntimeError(str(msg)) from None
    except urllib.error.URLError as e:
        raise RuntimeError(f"Could not reach Supabase. Check SUPABASE_URL: {e}") from None


def _profile_from_response(payload: Dict, fallback_email: str = "", fallback_name: str = "") -> Dict:
    user = payload.get("user") or payload
    metadata = user.get("user_metadata") or {}
    email = (user.get("email") or fallback_email or "").strip().lower()
    if not email:
        raise RuntimeError("Supabase did not return an email address.")
    session = payload.get("session") or {}
    return {
        "email": email,
        "name": metadata.get("name") or metadata.get("full_name") or fallback_name or email.split("@")[0],
        "picture": metadata.get("avatar_url") or metadata.get("picture") or "",
        "access_token": session.get("access_token") or payload.get("access_token") or "",
    }


def sign_up(email: str, password: str, name: str = "") -> Dict:
    payload = _post("/auth/v1/signup", {
        "email": email,
        "password": password,
        "data": {"name": name, "full_name": name},
    })
    return _profile_from_response(payload, fallback_email=email, fallback_name=name)


def sign_in_with_password(email: str, password: str) -> Dict:
    payload = _post("/auth/v1/token?grant_type=password", {
        "email": email,
        "password": password,
    })
    return _profile_from_response(payload, fallback_email=email)


def send_password_reset(email: str) -> None:
    redirect_to = os.getenv("SUPABASE_PASSWORD_REDIRECT", "").strip()
    body = {"email": email}
    if redirect_to:
        body["redirect_to"] = redirect_to
    _post("/auth/v1/recover", body)
