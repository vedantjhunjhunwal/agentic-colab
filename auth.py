"""Authentication: Google OAuth 2.0 with a demo fallback.

Real Google sign-in activates automatically when these env vars are set:

    GOOGLE_CLIENT_ID
    GOOGLE_CLIENT_SECRET

(create them at https://console.cloud.google.com → APIs & Services →
Credentials → OAuth client ID → Web application, and add your deployed
``/auth/google/callback`` URL as an authorised redirect URI).

When they are not set, the login page offers a one-click **demo** sign-in so
the app is fully usable locally and in environments without OAuth configured.
The two paths converge on the same user record, so notebooks persist either way.
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Dict

GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"


def is_google_configured() -> bool:
    return bool(os.getenv("GOOGLE_CLIENT_ID") and os.getenv("GOOGLE_CLIENT_SECRET"))


def configured_redirect_base() -> str:
    """An explicit public base URL for OAuth redirects, if the operator set one.

    On a LAN IP or behind a proxy, Flask's auto-generated callback URL can be
    wrong (it may say ``http://0.0.0.0:8080``). Set ``OAUTH_REDIRECT_BASE`` (or
    ``PUBLIC_BASE_URL``) to e.g. ``http://192.168.29.141:8501`` and the callback
    becomes ``<base>/auth/google/callback`` — this exact URL must also be listed
    as an authorised redirect URI in the Google Cloud console.
    """
    base = os.getenv("OAUTH_REDIRECT_BASE") or os.getenv("PUBLIC_BASE_URL") or ""
    return base.rstrip("/")


def google_auth_url(redirect_uri: str, state: str) -> str:
    params = {
        "client_id": os.getenv("GOOGLE_CLIENT_ID", ""),
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    return GOOGLE_AUTH_ENDPOINT + "?" + urllib.parse.urlencode(params)


def google_exchange_code(code: str, redirect_uri: str) -> Dict:
    """Exchange an authorization code for the user's profile."""
    data = urllib.parse.urlencode({
        "code": code,
        "client_id": os.getenv("GOOGLE_CLIENT_ID", ""),
        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET", ""),
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }).encode("utf-8")
    req = urllib.request.Request(
        GOOGLE_TOKEN_ENDPOINT, data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        token = json.loads(resp.read().decode("utf-8"))

    access_token = token.get("access_token")
    if not access_token:
        raise RuntimeError("Google did not return an access token")

    info_req = urllib.request.Request(
        GOOGLE_USERINFO_ENDPOINT,
        headers={"Authorization": f"Bearer {access_token}"},
    )
    with urllib.request.urlopen(info_req, timeout=30) as resp:
        profile = json.loads(resp.read().decode("utf-8"))

    return {
        "email": profile.get("email", ""),
        "name": profile.get("name", ""),
        "picture": profile.get("picture", ""),
        "provider": "google",
    }
