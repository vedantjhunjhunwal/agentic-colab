"""Supabase Auth adapter for Agentic AI DSL Colab.

Uses Supabase Auth over HTTPS, so it works on Render without SMTP/OTP
email-provider setup. Existing local notebook storage remains unchanged: after
Supabase verifies a user, the app maps that email to the local users table.

Required env vars:
    SUPABASE_URL=https://xxxx.supabase.co
    SUPABASE_ANON_KEY=eyJ...
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, Optional


def is_configured() -> bool:
    return bool(os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_ANON_KEY"))


def _base_url() -> str:
    return os.getenv("SUPABASE_URL", "").rstrip("/")


def _anon_key() -> str:
    return os.getenv("SUPABASE_ANON_KEY", "").strip()


def _headers() -> dict:
    key = _anon_key()
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "User-Agent": "agentic-colab/1.0",
    }


def _post(path: str, payload: dict, query: Optional[dict] = None) -> Dict:
    if not is_configured():
        raise RuntimeError("Supabase Auth is not configured. Set SUPABASE_URL and SUPABASE_ANON_KEY.")
    url = _base_url() + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=_headers(), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            text = resp.read().decode("utf-8")
            return json.loads(text) if text else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "ignore")
        try:
            parsed = json.loads(detail)
            msg = parsed.get("msg") or parsed.get("message") or parsed.get("error_description") or detail
        except Exception:
            msg = detail or str(exc)
        raise RuntimeError(msg) from exc


def signup(email: str, password: str, name: str = "") -> Dict:
    payload = {
        "email": email,
        "password": password,
        "data": {"name": name, "full_name": name},
    }
    return _post("/auth/v1/signup", payload)


def signin(email: str, password: str) -> Dict:
    return _post("/auth/v1/token", {"email": email, "password": password}, {"grant_type": "password"})


def recover_password(email: str, redirect_to: str = "") -> Dict:
    payload = {"email": email}
    if redirect_to:
        payload["redirect_to"] = redirect_to
    return _post("/auth/v1/recover", payload)


def profile_from_auth_response(data: Dict, fallback_email: str = "", fallback_name: str = "") -> Dict:
    user = data.get("user") or {}
    meta = user.get("user_metadata") or {}
    email = (user.get("email") or fallback_email or "").strip().lower()
    name = (meta.get("name") or meta.get("full_name") or fallback_name or (email.split("@")[0] if email else "User"))
    return {"email": email, "name": name, "picture": meta.get("avatar_url", ""), "provider": "supabase"}
