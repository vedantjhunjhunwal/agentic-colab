"""Agentic AI DSL Colab — a Google Colab-style notebook with the Python-like
AIDL (Agentic AI DSL) language, persistent storage, Google login, dataset
import (upload + Kaggle), notebook sharing/collaboration, and a built-in
agentic assistant.

Run locally:    python app.py
Production:     gunicorn -b 0.0.0.0:8080 app:app
"""
from __future__ import annotations

import os
import secrets
from functools import wraps
from pathlib import Path


# ===========================================================================
#  Load environment variables from .env  (MUST run before anything reads them)
# ===========================================================================
def _load_env_file():
    here = Path(__file__).resolve().parent
    # Cover the common cases, including the Windows ".env.txt" gotcha
    candidates = [
        here / ".env",
        here / ".env.txt",
        Path.cwd() / ".env",
        Path.cwd() / ".env.txt",
    ]
    try:
        from dotenv import load_dotenv
    except ImportError:
        print("=" * 64)
        print(" WARNING: python-dotenv is NOT installed.")
        print(" Your .env file will NOT be loaded, so MAIL_USERNAME /")
        print(" MAIL_PASSWORD will be missing and OTP email will not work.")
        print("")
        print("   Fix:  pip install python-dotenv")
        print("")
        print(" (Or set the variables directly in your terminal — see README.)")
        print("=" * 64)
        return
    for path in candidates:
        if path.exists():
            load_dotenv(path, override=True)
            print(f"[env] Loaded environment variables from: {path}")
            return
    print("[env] No .env file found. Looked in:")
    for p in candidates:
        print(f"        - {p}")
    print("[env] Create one (copy .env.example to .env) or set vars in the terminal.")


_load_env_file()

# Warn if running under the Microsoft Store Python build, which has a very long
# sandboxed install path that breaks large package installs (torch, tensorflow)
# unless Windows Long Path support is enabled.
import sys as _sys
if "windowsapps" in _sys.executable.lower() or \
   "pythonsoftwarefoundation.python" in _sys.executable.lower():
    print("=" * 64)
    print(" [warning] You are using the Microsoft Store build of Python:")
    print(f"   {_sys.executable}")
    print(" Heavy packages like torch/tensorflow may fail to install here due")
    print(" to Windows' 260-char path limit. If 'pip install torch' fails:")
    print("   • Enable Long Path support (PowerShell as Admin), then reboot:")
    print("     Set-ItemProperty -Path 'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\FileSystem' "
          "-Name 'LongPathsEnabled' -Value 1")
    print("   • OR install Python from python.org (shorter path, recommended).")
    print("=" * 64)

# Startup diagnostics — confirms whether mail credentials were picked up.
# The password itself is NEVER printed, only whether it was found.
print(f"[env] MAIL_USERNAME      : {os.getenv('MAIL_USERNAME') or '(not set)'}")
print(f"[env] MAIL_PASSWORD found: {bool(os.getenv('MAIL_PASSWORD'))}")

from flask import (
    Flask, abort, jsonify, redirect, render_template, render_template_string,
    request, send_from_directory, session, url_for,
)

try:
    from werkzeug.middleware.proxy_fix import ProxyFix
except Exception:  # pragma: no cover
    ProxyFix = None

import agent
import auth
import mailer
import storage
import supabase_auth
from kernel import KernelManager
from manual import AIDL_MANUAL

BASE_DIR = Path(__file__).resolve().parent

app = Flask(__name__, template_folder="templates", static_folder="static")
if ProxyFix is not None:
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)


def _load_secret() -> str:
    env = os.getenv("COLAB_SECRET")
    if env:
        return env
    storage.DATA_ROOT.mkdir(parents=True, exist_ok=True)
    key_file = storage.DATA_ROOT / "secret.key"
    if key_file.exists():
        return key_file.read_text().strip()
    key = secrets.token_hex(32)
    key_file.write_text(key)
    return key


app.secret_key = _load_secret()
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024  # 500 MB uploads

storage.init_db()
mailer.init_mail(app)
kernels = KernelManager()

import time as _time_module  # noqa – used by reset_password

ENABLE_2FA = os.getenv("ENABLE_2FA", "true").lower() != "false"


# ---- helpers -------------------------------------------------------------
def current_user():
    uid = session.get("uid")
    return storage.get_user(uid) if uid else None


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("uid"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "not authenticated"}), 401
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def accessible_notebook_or_404(notebook_id):
    """Return the notebook if the current user owns it or it's shared with them."""
    user = current_user()
    if not user:
        abort(401)
    nb = storage.get_accessible_notebook(notebook_id, user)
    if not nb:
        abort(404)
    return nb


def _oauth_redirect_uri():
    base = auth.configured_redirect_base()
    if base:
        return base + "/auth/google/callback"
    return url_for("auth_google_callback", _external=True)


# ==========================================================================
#  Pages
# ==========================================================================
@app.route("/")
def index():
    if session.get("uid"):
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login")
def login():
    if session.get("uid"):
        return redirect(url_for("dashboard"))
    return render_template("login.html",
                           google_enabled=auth.is_google_configured(),
                           supabase_enabled=supabase_auth.is_configured(),
                           error=request.args.get("error"),
                           prefill_email=request.args.get("prefill_email"))


@app.route("/auth/demo", methods=["POST"])
def auth_demo():
    email = (request.form.get("email") or "").strip().lower()
    name = (request.form.get("name") or "").strip()
    if not email or "@" not in email:
        email = f"guest_{secrets.token_hex(3)}@demo.local"
        name = name or "Guest"
    user = storage.upsert_user(email=email, name=name, provider="demo")
    session["uid"] = user["id"]
    return redirect(url_for("dashboard"))


def _mask_email(email: str) -> str:
    user, _, domain = email.partition("@")
    return (user[:1] + "***@" + domain) if domain else "your email"


# ==========================================================================
#  Password-based login (+ 2FA OTP)
# ==========================================================================
@app.route("/auth/password", methods=["POST"])
def auth_password_login():
    from werkzeug.security import check_password_hash
    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password", "")
    if not email or not password:
        return redirect(url_for("login", error="Email and password are required."))

    # Supabase mode: keep the same login form, but verify the password through
    # Supabase Auth over HTTPS. No SMTP/Resend OTP is needed on Render.
    if supabase_auth.is_configured():
        try:
            data = supabase_auth.signin(email, password)
            profile = supabase_auth.profile_from_auth_response(data, fallback_email=email)
        except Exception as exc:  # noqa: BLE001
            msg = str(exc) or "Could not sign in with Supabase."
            if "Email not confirmed" in msg:
                msg = "Please verify your email from the Supabase confirmation link, then sign in."
            return redirect(url_for("login", error=msg, prefill_email=email))
        user = storage.upsert_user(**profile)
        session["uid"] = user["id"]
        return redirect(url_for("dashboard"))

    user = storage.get_user_by_email(email)
    if not user or not user.get("password_hash"):
        return redirect(url_for("login",
            error="No account found with that email.", prefill_email=email))
    if not check_password_hash(user["password_hash"], password):
        return redirect(url_for("login", error="Incorrect password.", prefill_email=email))
    if ENABLE_2FA:
        otp = mailer.generate_otp()
        storage.store_otp(email, mailer.hash_otp(otp), purpose="2fa")
        result = mailer.send_otp(email, otp, "2fa")
        if result:  # send failed
            return redirect(url_for("login", error=result))
        session["pending_2fa_uid"]   = user["id"]
        session["pending_2fa_email"] = email
        return redirect(url_for("auth_verify_otp_page", purpose="2fa"))
    session["uid"] = user["id"]
    return redirect(url_for("dashboard"))


# ==========================================================================
#  Registration with OTP email verification
# ==========================================================================
@app.route("/auth/register", methods=["GET", "POST"])
def auth_register():
    from werkzeug.security import generate_password_hash
    if request.method == "GET":
        return render_template("register.html",
                               error=request.args.get("error"),
                               prefill_email=request.args.get("email"),
                               prefill_name=request.args.get("name"))
    name  = (request.form.get("name")     or "").strip()
    email = (request.form.get("email")    or "").strip().lower()
    pwd   = request.form.get("password",    "")
    conf  = request.form.get("confirm",     "")

    def rereg(err):
        return render_template("register.html", error=err,
                               prefill_email=email, prefill_name=name)

    if not name or not email or not pwd:
        return rereg("All fields are required.")
    if "@" not in email:
        return rereg("Enter a valid email address.")
    if len(pwd) < 8:
        return rereg("Password must be at least 8 characters.")
    if pwd != conf:
        return rereg("Passwords do not match.")
    existing = storage.get_user_by_email(email)
    if existing and existing.get("password_hash") and not supabase_auth.is_configured():
        return rereg("An account already exists with that email. Sign in instead.")

    # Supabase mode: keep the same registration form, but let Supabase handle
    # account creation and email verification. This avoids Resend/Gmail SMTP.
    if supabase_auth.is_configured():
        try:
            data = supabase_auth.signup(email, pwd, name)
            profile = supabase_auth.profile_from_auth_response(data, fallback_email=email, fallback_name=name)
        except Exception as exc:  # noqa: BLE001
            return rereg(str(exc) or "Could not create account with Supabase.")
        # If Supabase email confirmations are disabled, a session may be returned
        # immediately. If confirmations are enabled, ask the user to verify first.
        if data.get("session") or data.get("access_token"):
            user = storage.upsert_user(**profile)
            session["uid"] = user["id"]
            return redirect(url_for("dashboard"))
        return redirect(url_for("login",
            error="✓ Account created. Check your email, verify it, then sign in.",
            prefill_email=email))

    pwd_hash = generate_password_hash(pwd, method="pbkdf2:sha256")
    storage.store_pending_registration(email, name, pwd_hash)
    otp = mailer.generate_otp()
    storage.store_otp(email, mailer.hash_otp(otp), purpose="register")
    result = mailer.send_otp(email, otp, "register")
    if result:  # send failed (mail not configured or SMTP error)
        storage.pop_pending_registration(email)
        return rereg(result)
    session["otp_flow_email"] = email
    return redirect(url_for("auth_verify_otp_page", purpose="register"))


# ==========================================================================
#  OTP verification page + POST handler
# ==========================================================================
@app.route("/auth/otp", methods=["GET"])
def auth_verify_otp_page():
    purpose = request.args.get("purpose", "2fa")
    error   = request.args.get("error")
    if purpose == "2fa":
        email = session.get("pending_2fa_email", "")
    else:
        email = session.get("otp_flow_email", "")
    masked = _mask_email(email) if email else request.args.get("masked", "your email")
    return render_template("otp.html", purpose=purpose, error=error, masked_email=masked)


@app.route("/auth/otp", methods=["POST"])
def auth_verify_otp():
    purpose     = request.form.get("purpose", "2fa")
    otp_entered = (request.form.get("otp") or "").strip()
    if not otp_entered or len(otp_entered) != 6 or not otp_entered.isdigit():
        return redirect(url_for("auth_verify_otp_page", purpose=purpose,
                                error="Enter the 6-digit code."))
    if purpose == "2fa":
        email = session.get("pending_2fa_email", "")
        uid   = session.get("pending_2fa_uid")
    else:
        email = session.get("otp_flow_email", "")
        uid   = None
    if not email:
        return redirect(url_for("login", error="Session expired. Please try again."))
    outcome = storage.verify_and_consume_otp(email, mailer.hash_otp(otp_entered), purpose)
    if outcome == "expired":
        return redirect(url_for("auth_verify_otp_page", purpose=purpose,
                                error="This code has expired. Request a new one."))
    if outcome != "ok":
        return redirect(url_for("auth_verify_otp_page", purpose=purpose,
                                error="Incorrect code — try again."))
    if purpose == "2fa":
        session.pop("pending_2fa_uid",   None)
        session.pop("pending_2fa_email", None)
        session["uid"] = uid
        return redirect(url_for("dashboard"))
    if purpose == "register":
        pending = storage.pop_pending_registration(email)
        if not pending:
            return redirect(url_for("auth_register",
                error="Registration session expired. Please register again.", email=email))
        user = storage.create_password_user(email, pending["name"], pending["pwd_hash"])
        session.pop("otp_flow_email", None)
        session["uid"] = user["id"]
        return redirect(url_for("dashboard"))
    if purpose == "forgot_password":
        session["reset_email"] = email
        session["reset_at"]    = _time_module.time()
        session.pop("otp_flow_email", None)
        return redirect(url_for("auth_reset_password"))
    return redirect(url_for("login"))


@app.route("/auth/resend-otp", methods=["POST"])
def auth_resend_otp():
    email = (session.get("otp_flow_email") or session.get("pending_2fa_email") or "")
    if not email:
        return jsonify({"error": "Session expired. Please start again."}), 400
    purpose = "2fa" if session.get("pending_2fa_email") else "register"
    otp = mailer.generate_otp()
    storage.store_otp(email, mailer.hash_otp(otp), purpose=purpose)
    result = mailer.send_otp(email, otp, purpose)
    if result:
        return jsonify({"error": result}), 503
    return jsonify({"ok": True})


# ==========================================================================
#  Forgot password + reset password
# ==========================================================================
@app.route("/auth/forgot-password", methods=["GET", "POST"])
def auth_forgot_password():
    if request.method == "GET":
        return render_template("forgot_password.html", error=request.args.get("error"))
    email = (request.form.get("email") or "").strip().lower()
    if not email or "@" not in email:
        return render_template("forgot_password.html",
                               error="Enter a valid email address.")
    user = storage.get_user_by_email(email)
    if not user or not user.get("password_hash"):
        # Redirect without error to prevent email enumeration, but if mail is
        # not configured we must surface the config issue to the form
        if not mailer.is_configured():
            return render_template("forgot_password.html",
                                   error="Email is not configured on this server. "
                                         "Set MAIL_USERNAME and MAIL_PASSWORD to enable password reset.")
        # Unknown email — redirect anyway (anti-enumeration)
        return redirect(url_for("auth_verify_otp_page", purpose="forgot_password"))
    if not mailer.is_configured():
        return render_template("forgot_password.html",
                               error="Email is not configured on this server. "
                                     "Set MAIL_USERNAME and MAIL_PASSWORD to enable password reset.")
    otp = mailer.generate_otp()
    storage.store_otp(email, mailer.hash_otp(otp), purpose="forgot_password")
    result = mailer.send_otp(email, otp, "forgot_password")
    if result:  # SMTP error
        return render_template("forgot_password.html", error=result)
    session["otp_flow_email"] = email
    # Redirect without revealing whether the email exists (anti-enumeration)
    return redirect(url_for("auth_verify_otp_page", purpose="forgot_password"))


@app.route("/auth/reset-password", methods=["GET", "POST"])
def auth_reset_password():
    from werkzeug.security import generate_password_hash
    reset_email = session.get("reset_email")
    reset_at    = session.get("reset_at", 0)
    if not reset_email or (_time_module.time() - reset_at) > 600:
        return redirect(url_for("auth_forgot_password",
                                error="Reset session expired. Please start again."))
    if request.method == "GET":
        return render_template("reset_password.html", error=request.args.get("error"))
    pwd  = request.form.get("password", "")
    conf = request.form.get("confirm", "")
    if len(pwd) < 8:
        return render_template("reset_password.html",
                               error="Password must be at least 8 characters.")
    if pwd != conf:
        return render_template("reset_password.html", error="Passwords do not match.")
    storage.update_password(reset_email, generate_password_hash(pwd, method="pbkdf2:sha256"))
    session.pop("reset_email", None)
    session.pop("reset_at",    None)
    return redirect(url_for("login",
                            error="✓ Password updated — sign in with your new password."))


@app.route("/auth/google")
def auth_google():
    if not auth.is_google_configured():
        return redirect(url_for("login"))
    state = secrets.token_urlsafe(16)
    session["oauth_state"] = state
    return redirect(auth.google_auth_url(_oauth_redirect_uri(), state))


_OAUTH_ERROR_HTML = """<!doctype html><html><head><meta charset='utf-8'>
<title>Sign-in error</title><meta name='viewport' content='width=device-width, initial-scale=1'>
<style>body{font-family:system-ui,Segoe UI,Roboto,sans-serif;background:#f9fbfd;margin:0;
display:flex;min-height:100vh;align-items:center;justify-content:center}
.card{background:#fff;border:1px solid #e8eaed;border-radius:14px;box-shadow:0 1px 3px rgba(60,64,67,.3);
max-width:560px;padding:32px 36px}.h{font-size:20px;font-weight:500;margin:0 0 10px;color:#3c4043}
p{color:#5f6368;line-height:1.6}code{background:#f1f3f4;padding:2px 6px;border-radius:4px;font-size:13px}
a{display:inline-block;margin-top:16px;color:#1a73e8}</style></head>
<body><div class='card'><p class='h'>Google sign-in could not complete</p>
<p>{{ detail }}</p>
<p>The most common cause is a <strong>redirect-URI mismatch</strong>. In the Google Cloud
console (APIs &amp; Services → Credentials → your OAuth client), add this exact
authorised redirect URI:</p>
<p><code>{{ redirect_uri }}</code></p>
<p>If your server is reached at a different host/port than it sees internally, also set the
<code>OAUTH_REDIRECT_BASE</code> environment variable to your public URL (e.g.
<code>http://192.168.29.141:8501</code>) and restart.</p>
<a href='{{ login_url }}'>← Back to sign in</a></div></body></html>"""


@app.route("/auth/google/callback")
def auth_google_callback():
    if request.args.get("error"):
        return render_template_string(
            _OAUTH_ERROR_HTML, detail=f"Google returned: {request.args.get('error')}",
            redirect_uri=_oauth_redirect_uri(), login_url=url_for("login")), 400
    if request.args.get("state") != session.get("oauth_state"):
        return render_template_string(
            _OAUTH_ERROR_HTML, detail="The sign-in session expired or the state did not match. "
            "Please try again.", redirect_uri=_oauth_redirect_uri(), login_url=url_for("login")), 400
    code = request.args.get("code")
    if not code:
        return render_template_string(
            _OAUTH_ERROR_HTML, detail="No authorization code was returned.",
            redirect_uri=_oauth_redirect_uri(), login_url=url_for("login")), 400
    try:
        profile = auth.google_exchange_code(code, _oauth_redirect_uri())
    except Exception as exc:  # noqa: BLE001
        return render_template_string(
            _OAUTH_ERROR_HTML, detail=f"Token exchange failed: {exc}",
            redirect_uri=_oauth_redirect_uri(), login_url=url_for("login")), 400
    if not profile.get("email"):
        return render_template_string(
            _OAUTH_ERROR_HTML, detail="Google did not return an email address.",
            redirect_uri=_oauth_redirect_uri(), login_url=url_for("login")), 400
    user = storage.upsert_user(**profile)
    session["uid"] = user["id"]
    return redirect(url_for("dashboard"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    user = current_user()
    notebooks = storage.list_notebooks(user)
    return render_template("dashboard.html", user=user, notebooks=notebooks)


@app.route("/notebook/<notebook_id>")
@login_required
def notebook(notebook_id):
    nb = accessible_notebook_or_404(notebook_id)
    user = current_user()
    collaborators = storage.list_collaborators(notebook_id)
    return render_template(
        "notebook.html",
        user=user,
        notebook=nb,
        role=nb.get("role", "owner"),
        is_owner=(nb.get("role") == "owner"),
        owner_email=nb.get("owner_email"),
        collaborators=collaborators,
        google_enabled=auth.is_google_configured(),
    )


# ==========================================================================
#  Notebook API
# ==========================================================================
@app.route("/api/notebooks", methods=["GET"])
@login_required
def api_list_notebooks():
    return jsonify(storage.list_notebooks(current_user()))


@app.route("/api/notebooks", methods=["POST"])
@login_required
def api_create_notebook():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "Untitled notebook").strip() or "Untitled notebook"
    nb = storage.create_notebook(session["uid"], name=name)
    return jsonify({"id": nb["id"], "name": nb["name"]})


@app.route("/api/notebooks/<notebook_id>", methods=["GET"])
@login_required
def api_get_notebook(notebook_id):
    nb = accessible_notebook_or_404(notebook_id)
    return jsonify(nb)


@app.route("/api/notebooks/<notebook_id>", methods=["PUT"])
@login_required
def api_save_notebook(notebook_id):
    accessible_notebook_or_404(notebook_id)
    data = request.get_json(silent=True) or {}
    content = data.get("content")
    name = data.get("name")
    if content is None:
        return jsonify({"error": "content required"}), 400
    storage.update_notebook(notebook_id, content, name=name)
    return jsonify({"status": "saved"})


@app.route("/api/notebooks/<notebook_id>/rename", methods=["POST"])
@login_required
def api_rename_notebook(notebook_id):
    accessible_notebook_or_404(notebook_id)
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    storage.set_notebook_name(notebook_id, name)
    return jsonify({"status": "renamed", "name": name})


@app.route("/api/notebooks/<notebook_id>", methods=["DELETE"])
@login_required
def api_delete_notebook(notebook_id):
    nb = accessible_notebook_or_404(notebook_id)
    if nb.get("role") != "owner":
        return jsonify({"error": "only the owner can delete this notebook"}), 403
    kernels.drop(notebook_id)
    storage.delete_notebook(notebook_id, session["uid"])
    return jsonify({"status": "deleted"})


@app.route("/api/notebooks/<notebook_id>/run", methods=["POST"])
@login_required
def api_run_cell(notebook_id):
    nb = accessible_notebook_or_404(notebook_id)
    data = request.get_json(silent=True) or {}
    source = data.get("source", "")
    language = data.get("language", "python")
    work_dir = storage.notebook_dir(nb["owner_id"], notebook_id)
    kernel = kernels.get(notebook_id, str(work_dir))
    result = kernel.execute(source, language=language)
    return jsonify(result)


@app.route("/api/notebooks/<notebook_id>/reset", methods=["POST"])
@login_required
def api_reset_kernel(notebook_id):
    nb = accessible_notebook_or_404(notebook_id)
    work_dir = storage.notebook_dir(nb["owner_id"], notebook_id)
    kernels.reset(notebook_id, str(work_dir))
    return jsonify({"status": "runtime restarted"})


# ==========================================================================
#  Sharing / collaboration
# ==========================================================================
@app.route("/api/notebooks/<notebook_id>/collaborators", methods=["GET"])
@login_required
def api_list_collaborators(notebook_id):
    nb = accessible_notebook_or_404(notebook_id)
    return jsonify({
        "owner_email": nb.get("owner_email"),
        "is_owner": nb.get("role") == "owner",
        "collaborators": storage.list_collaborators(notebook_id),
    })


@app.route("/api/notebooks/<notebook_id>/share", methods=["POST"])
@login_required
def api_share_notebook(notebook_id):
    accessible_notebook_or_404(notebook_id)
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    if not email or "@" not in email:
        return jsonify({"error": "a valid email is required"}), 400
    result = storage.share_notebook(notebook_id, session["uid"], email)
    if result.get("error"):
        return jsonify(result), 403
    return jsonify({"status": "shared", **result})


@app.route("/api/notebooks/<notebook_id>/share", methods=["DELETE"])
@login_required
def api_unshare_notebook(notebook_id):
    accessible_notebook_or_404(notebook_id)
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    ok = storage.unshare_notebook(notebook_id, session["uid"], email)
    return jsonify({"status": "removed" if ok else "not allowed"})


# ==========================================================================
#  Files / datasets API
# ==========================================================================
@app.route("/api/notebooks/<notebook_id>/files", methods=["GET"])
@login_required
def api_list_files(notebook_id):
    nb = accessible_notebook_or_404(notebook_id)
    return jsonify(storage.list_datasets(nb["owner_id"], notebook_id))


@app.route("/api/notebooks/<notebook_id>/files", methods=["POST"])
@login_required
def api_upload_file(notebook_id):
    nb = accessible_notebook_or_404(notebook_id)
    if "file" not in request.files:
        return jsonify({"error": "no file part"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "empty filename"}), 400
    info = storage.save_dataset(nb["owner_id"], notebook_id, f.filename, f)
    return jsonify({"status": "uploaded", **info})


@app.route("/api/notebooks/<notebook_id>/kaggle", methods=["POST"])
@login_required
def api_kaggle_import(notebook_id):
    nb = accessible_notebook_or_404(notebook_id)
    data = request.get_json(silent=True) or {}
    slug = data.get("dataset", "")
    username = data.get("username", "")
    key = data.get("key", "")
    result = storage.import_kaggle_dataset(nb["owner_id"], notebook_id, slug, username, key)
    status = 200 if not result.get("error") else 400
    return jsonify(result), status


@app.route("/api/notebooks/<notebook_id>/files/<path:filename>", methods=["DELETE"])
@login_required
def api_delete_file(notebook_id, filename):
    nb = accessible_notebook_or_404(notebook_id)
    ok = storage.delete_dataset(nb["owner_id"], notebook_id, filename)
    return jsonify({"status": "deleted" if ok else "not found"})


@app.route("/api/notebooks/<notebook_id>/files/<path:filename>/download", methods=["GET"])
@login_required
def api_download_file(notebook_id, filename):
    nb = accessible_notebook_or_404(notebook_id)
    p = storage.dataset_path(nb["owner_id"], notebook_id, filename)
    if not p:
        abort(404)
    return send_from_directory(p.parent, p.name, as_attachment=True)


# ==========================================================================
#  Agentic assistant API
# ==========================================================================
@app.route("/api/notebooks/<notebook_id>/explain", methods=["POST"])
@login_required
def api_explain(notebook_id):
    accessible_notebook_or_404(notebook_id)
    data = request.get_json(silent=True) or {}
    language = data.get("language", "python")
    code = data.get("code", "")
    error = data.get("error") or {}
    provider = data.get("provider")
    api_key = data.get("api_key")
    model = data.get("model", "")

    deterministic = agent.explain_error(language, code, error)
    md = agent.explanation_to_markdown(deterministic)

    if provider and api_key:
        prompt = (
            f"Explain this {language} error to a beginner and give a corrected snippet.\n\n"
            f"Code:\n```\n{code[:3000]}\n```\n\n"
            f"Error: {error.get('ename')}: {error.get('evalue')} (line {error.get('line')})"
        )
        try:
            text = agent.llm_reply(prompt, provider, api_key, model)
            return jsonify({"markdown": text, "mode": f"llm:{provider}", "deterministic": md})
        except Exception as exc:  # noqa: BLE001
            return jsonify({
                "markdown": md + f"\n\n_(LLM unavailable: {exc})_",
                "mode": "deterministic",
            })
    return jsonify({"markdown": md, "mode": "deterministic"})


@app.route("/api/notebooks/<notebook_id>/assistant", methods=["POST"])
@login_required
def api_assistant(notebook_id):
    accessible_notebook_or_404(notebook_id)
    data = request.get_json(silent=True) or {}
    message = data.get("message", "")
    context = {
        "language": data.get("language", "python"),
        "code": data.get("code", ""),
        "error": data.get("error"),
    }
    reply = agent.assistant_chat(
        message, context,
        provider=data.get("provider"),
        api_key=data.get("api_key"),
        model=data.get("model", ""),
    )
    return jsonify(reply)


@app.route("/api/aidl/manual", methods=["GET"])
def api_aidl_manual():
    return jsonify({"markdown": AIDL_MANUAL})


@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok", "service": "agentic-ai-dsl-colab"})


@app.route("/static/img/<path:filename>")
def static_img(filename):
    return send_from_directory(BASE_DIR / "static" / "img", filename)


def _can_bind(host: str, port: int) -> bool:
    """Return True if we can bind a TCP socket to host:port right now."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _start_server():
    """Start the dev server, choosing a host/port that actually binds.

    Handles the common Windows 'WinError 10013' case where the requested port
    is reserved by Hyper-V / WSL2 / Docker, by automatically trying alternates
    and (if needed) falling back from 0.0.0.0 to 127.0.0.1.
    """
    import sys
    requested_port = int(os.environ.get("PORT", 8080))
    requested_host = os.environ.get("HOST", "0.0.0.0")

    # Ports to try, starting with the requested one
    alt_ports = [requested_port, 8080, 8000, 5000, 3000, 5050, 8888, 8050, 0]
    seen = set()
    candidates = [p for p in alt_ports if not (p in seen or seen.add(p))]

    for host in (requested_host, "127.0.0.1"):
        for port in candidates:
            # port 0 lets the OS pick any free port (last resort)
            if port == 0 or _can_bind(host, port):
                if port != requested_port or host != requested_host:
                    print("=" * 64)
                    print(f" [server] Requested {requested_host}:{requested_port} was "
                          f"unavailable (in use or blocked by Windows).")
                    print(f" [server] Using {host}:{port if port else '(auto)'} instead.")
                    print("=" * 64)
                shown_host = "127.0.0.1" if host == "0.0.0.0" else host
                if port:
                    print(f"\n  ➜  Open http://{shown_host}:{port}\n")
                try:
                    app.run(host=host, port=port,
                            debug=bool(os.environ.get("FLASK_DEBUG")))
                    return
                except OSError as exc:
                    print(f" [server] Could not start on {host}:{port} ({exc}). Trying next…")
                    continue
        # if we exhausted ports on requested_host, loop falls back to 127.0.0.1

    print("=" * 64)
    print(" [server] Could not bind to any port. To fix on Windows:")
    print("   1) Close any other running copy of this app (check Task Manager).")
    print("   2) Pick a specific port:   set PORT=8080   (PowerShell: $env:PORT=8080)")
    print("   3) See which ranges Windows reserved:")
    print("        netsh interface ipv4 show excludedportrange protocol=tcp")
    print("      and choose a PORT outside those ranges.")
    print("=" * 64)
    sys.exit(1)


if __name__ == "__main__":
    _start_server()
