"""Persistence for Agentic Colab.

* **SQLite** stores users and notebook documents (cells + saved outputs).
* **Filesystem** stores uploaded datasets, one folder per notebook, which is
  also the notebook's runtime working directory.

Everything a user does — every notebook, every cell, the output of each run,
and every uploaded dataset — survives a server restart.
"""
from __future__ import annotations

import json
import os
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Dict, List, Optional

# Resolve to an ABSOLUTE path so the database is found even if a notebook cell
# changes the process working directory (a relative path like ./data would
# otherwise break after running a cell). .resolve() makes it absolute.
DATA_ROOT = Path(os.environ.get("COLAB_DATA_DIR") or
                 (Path(__file__).resolve().parent / "data")).resolve()
DB_PATH = (DATA_ROOT / "colab.db").resolve()
FILES_ROOT = (DATA_ROOT / "users").resolve()


def _now() -> float:
    return time.time()


def _connect() -> sqlite3.Connection:
    # Ensure the data directory exists before opening (idempotent, cheap).
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def init_db():
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    FILES_ROOT.mkdir(parents=True, exist_ok=True)
    conn = _connect()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id        TEXT PRIMARY KEY,
            email     TEXT UNIQUE NOT NULL,
            name      TEXT,
            picture   TEXT,
            provider  TEXT,
            created_at REAL
        );
        CREATE TABLE IF NOT EXISTS notebooks (
            id         TEXT PRIMARY KEY,
            owner_id   TEXT NOT NULL,
            name       TEXT NOT NULL,
            content    TEXT NOT NULL,
            created_at REAL,
            updated_at REAL,
            FOREIGN KEY (owner_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS notebook_shares (
            notebook_id TEXT NOT NULL,
            email       TEXT NOT NULL,
            role        TEXT DEFAULT 'editor',
            created_at  REAL,
            PRIMARY KEY (notebook_id, email)
        );
        CREATE TABLE IF NOT EXISTS otp_store (
            id          TEXT PRIMARY KEY,
            email       TEXT NOT NULL,
            otp_hash    TEXT NOT NULL,
            purpose     TEXT NOT NULL,
            expires_at  REAL NOT NULL,
            used        INTEGER DEFAULT 0,
            created_at  REAL
        );
        CREATE TABLE IF NOT EXISTS pending_registrations (
            email      TEXT PRIMARY KEY,
            name       TEXT,
            pwd_hash   TEXT NOT NULL,
            expires_at REAL NOT NULL,
            created_at REAL
        );
        """
    )
    # Add password_hash column if it doesn't exist (idempotent migration)
    try:
        conn.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
        conn.commit()
    except Exception:
        pass  # column already exists
    conn.commit()
    conn.close()


# --------------------------------------------------------------------------
#  Users
# --------------------------------------------------------------------------
def upsert_user(email: str, name: str = "", picture: str = "", provider: str = "demo") -> Dict:
    email = email.strip().lower()
    conn = _connect()
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if row:
        conn.execute(
            "UPDATE users SET name = COALESCE(NULLIF(?, ''), name), "
            "picture = COALESCE(NULLIF(?, ''), picture), provider = ? WHERE email = ?",
            (name, picture, provider, email),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    else:
        uid = "u_" + secrets.token_hex(8)
        conn.execute(
            "INSERT INTO users (id, email, name, picture, provider, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (uid, email, name or email.split("@")[0], picture, provider, _now()),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    conn.close()
    return dict(row)


# --------------------------------------------------------------------------
#  Password-based auth
# --------------------------------------------------------------------------
def create_password_user(email: str, name: str, password_hash: str) -> Dict:
    """Create (or convert) a user with a password hash."""
    email = email.strip().lower()
    conn = _connect()
    existing = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if existing:
        conn.execute(
            "UPDATE users SET name = COALESCE(NULLIF(?, ''), name), "
            "password_hash = ?, provider = 'password' WHERE email = ?",
            (name, password_hash, email),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    else:
        uid = "u_" + secrets.token_hex(8)
        conn.execute(
            "INSERT INTO users (id, email, name, picture, provider, password_hash, created_at) "
            "VALUES (?, ?, ?, '', 'password', ?, ?)",
            (uid, email, name or email.split("@")[0], password_hash, _now()),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    conn.close()
    return dict(row)


def get_user_by_email(email: str) -> Optional[Dict]:
    email = email.strip().lower()
    conn = _connect()
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    conn.close()
    return dict(row) if row else None


def update_password(email: str, new_hash: str) -> bool:
    email = email.strip().lower()
    conn = _connect()
    cur = conn.execute(
        "UPDATE users SET password_hash = ? WHERE email = ?", (new_hash, email)
    )
    conn.commit()
    changed = cur.rowcount > 0
    conn.close()
    return changed


# --------------------------------------------------------------------------
#  OTP store
# --------------------------------------------------------------------------
def store_otp(email: str, otp_hash: str, purpose: str, ttl: int = 300) -> str:
    """Persist an OTP hash, invalidating any previous OTPs for the same
    email+purpose. Returns the new record id."""
    email = email.strip().lower()
    conn = _connect()
    # Expire previous OTPs for same email+purpose
    conn.execute(
        "UPDATE otp_store SET used = 1 WHERE email = ? AND purpose = ? AND used = 0",
        (email, purpose),
    )
    otp_id = secrets.token_hex(16)
    conn.execute(
        "INSERT INTO otp_store (id, email, otp_hash, purpose, expires_at, used, created_at) "
        "VALUES (?, ?, ?, ?, ?, 0, ?)",
        (otp_id, email, otp_hash, purpose, _now() + ttl, _now()),
    )
    conn.commit()
    conn.close()
    return otp_id


def verify_and_consume_otp(email: str, otp_hash: str, purpose: str) -> str:
    """Verify an OTP hash and mark it used.

    Returns 'ok', 'expired', 'invalid', or 'not_found'.
    """
    email = email.strip().lower()
    conn = _connect()
    row = conn.execute(
        "SELECT id, otp_hash, expires_at, used FROM otp_store "
        "WHERE email = ? AND purpose = ? AND used = 0 "
        "ORDER BY created_at DESC LIMIT 1",
        (email, purpose),
    ).fetchone()
    if not row:
        conn.close()
        return "not_found"
    if _now() > row["expires_at"]:
        conn.close()
        return "expired"
    if not secrets.compare_digest(row["otp_hash"], otp_hash):
        conn.close()
        return "invalid"
    conn.execute("UPDATE otp_store SET used = 1 WHERE id = ?", (row["id"],))
    conn.commit()
    conn.close()
    return "ok"


def cleanup_expired_otps():
    conn = _connect()
    conn.execute("DELETE FROM otp_store WHERE expires_at < ?", (_now() - 3600,))
    conn.execute("DELETE FROM pending_registrations WHERE expires_at < ?", (_now(),))
    conn.commit()
    conn.close()


# --------------------------------------------------------------------------
#  Pending registrations (email → password_hash, awaiting OTP confirmation)
# --------------------------------------------------------------------------
def store_pending_registration(email: str, name: str, pwd_hash: str, ttl: int = 600):
    email = email.strip().lower()
    conn = _connect()
    conn.execute(
        "INSERT OR REPLACE INTO pending_registrations "
        "(email, name, pwd_hash, expires_at, created_at) VALUES (?, ?, ?, ?, ?)",
        (email, name, pwd_hash, _now() + ttl, _now()),
    )
    conn.commit()
    conn.close()


def pop_pending_registration(email: str) -> Optional[Dict]:
    """Return and delete a pending registration if it exists and hasn't expired."""
    email = email.strip().lower()
    conn = _connect()
    row = conn.execute(
        "SELECT * FROM pending_registrations WHERE email = ? AND expires_at > ?",
        (email, _now()),
    ).fetchone()
    if row:
        conn.execute("DELETE FROM pending_registrations WHERE email = ?", (email,))
        conn.commit()
    conn.close()
    return dict(row) if row else None


def get_user(user_id: str) -> Optional[Dict]:
    conn = _connect()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


# --------------------------------------------------------------------------
#  Notebooks
# --------------------------------------------------------------------------
def _default_content(name: str) -> Dict:
    """A fresh notebook with a welcome text cell and starter code cell."""
    return {
        "cells": [
            {
                "id": "c_" + secrets.token_hex(4),
                "type": "text",
                "language": "markdown",
                "source": f"# {name}\n\nWelcome to **Agentic AI DSL Colab**. Each code cell shows a **language selector** at its top — switch between **Python 3** and **AIDL**. Upload datasets or import from **Kaggle** in the Files panel. Use **Share** to collaborate, and the **Assistant** to explain errors.",
                "outputs": [],
            },
            {
                "id": "c_" + secrets.token_hex(4),
                "type": "code",
                "language": "python",
                "source": "# Python 3 — full scientific stack + shell commands\nimport sys\nprint('Python', sys.version.split()[0])\n# Use !pip install <pkg> to install packages, %%writefile to create files\nfor i in range(3):\n    print('row', i)",
                "outputs": [],
            },
            {
                "id": "c_" + secrets.token_hex(4),
                "type": "code",
                "language": "aidl",
                "source": "# AIDL — Agentic AI DSL (Python-like, first-class ML)\nprint(\"Hello from AIDL\")\n\n# Upload a CSV in Files, then:\n# data = load(\"data.csv\")\n# model = classifier(algorithm=\"random_forest\")\n# model.train(data, epochs=20)\n# print(\"accuracy\", model.accuracy)\n\n# More: cluster(), decompose(), neural_network(), reinforce(), generate(), agent()",
                "outputs": [],
            },
        ]
    }


def create_notebook(owner_id: str, name: str = "Untitled notebook", content: Optional[Dict] = None) -> Dict:
    nid = "nb_" + secrets.token_hex(8)
    content = content or _default_content(name)
    conn = _connect()
    conn.execute(
        "INSERT INTO notebooks (id, owner_id, name, content, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (nid, owner_id, name, json.dumps(content), _now(), _now()),
    )
    conn.commit()
    conn.close()
    notebook_dir(owner_id, nid).mkdir(parents=True, exist_ok=True)
    return get_notebook(nid, owner_id)


def list_notebooks(user) -> List[Dict]:
    """List notebooks owned by *user* plus those shared with the user's email.

    ``user`` may be a user dict (with id+email) or a bare owner id string
    (back-compatible — shared notebooks are then omitted)."""
    if isinstance(user, str):
        owner_id, email = user, None
    else:
        owner_id, email = user["id"], user.get("email")
    conn = _connect()
    rows = conn.execute(
        "SELECT id, name, owner_id, created_at, updated_at FROM notebooks "
        "WHERE owner_id = ? ORDER BY updated_at DESC",
        (owner_id,),
    ).fetchall()
    owned = []
    for r in rows:
        d = dict(r)
        d["file_count"] = len(list_datasets(d["owner_id"], d["id"]))
        d["shared"] = False
        d["role"] = "owner"
        owned.append(d)
    shared = []
    if email:
        srows = conn.execute(
            "SELECT n.id, n.name, n.owner_id, n.created_at, n.updated_at, u.email AS owner_email "
            "FROM notebook_shares s JOIN notebooks n ON n.id = s.notebook_id "
            "LEFT JOIN users u ON u.id = n.owner_id "
            "WHERE s.email = ? ORDER BY n.updated_at DESC",
            (email.strip().lower(),),
        ).fetchall()
        for r in srows:
            d = dict(r)
            d["file_count"] = len(list_datasets(d["owner_id"], d["id"]))
            d["shared"] = True
            d["role"] = "editor"
            shared.append(d)
    conn.close()
    return owned + shared


def _get_notebook_any(notebook_id: str) -> Optional[Dict]:
    conn = _connect()
    row = conn.execute("SELECT * FROM notebooks WHERE id = ?", (notebook_id,)).fetchone()
    owner_email = None
    if row:
        u = conn.execute("SELECT email FROM users WHERE id = ?", (row["owner_id"],)).fetchone()
        owner_email = u["email"] if u else None
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["content"] = json.loads(d["content"])
    d["owner_email"] = owner_email
    return d


def _is_shared_with(notebook_id: str, email: str) -> bool:
    if not email:
        return False
    conn = _connect()
    row = conn.execute(
        "SELECT 1 FROM notebook_shares WHERE notebook_id = ? AND email = ?",
        (notebook_id, email.strip().lower()),
    ).fetchone()
    conn.close()
    return row is not None


def get_accessible_notebook(notebook_id: str, user: Dict) -> Optional[Dict]:
    """Return the notebook if *user* is the owner or a collaborator, else None."""
    nb = _get_notebook_any(notebook_id)
    if not nb:
        return None
    if nb["owner_id"] == user["id"]:
        nb["role"] = "owner"
        nb["shared"] = False
        return nb
    if _is_shared_with(notebook_id, user.get("email", "")):
        nb["role"] = "editor"
        nb["shared"] = True
        return nb
    return None


def update_notebook(notebook_id: str, content: Dict, name: Optional[str] = None) -> bool:
    """Persist content (and optionally name) by id — access is enforced upstream."""
    conn = _connect()
    if name is not None:
        cur = conn.execute(
            "UPDATE notebooks SET content = ?, name = ?, updated_at = ? WHERE id = ?",
            (json.dumps(content), name, _now(), notebook_id),
        )
    else:
        cur = conn.execute(
            "UPDATE notebooks SET content = ?, updated_at = ? WHERE id = ?",
            (json.dumps(content), _now(), notebook_id),
        )
    conn.commit()
    changed = cur.rowcount > 0
    conn.close()
    return changed


def set_notebook_name(notebook_id: str, name: str) -> bool:
    conn = _connect()
    cur = conn.execute(
        "UPDATE notebooks SET name = ?, updated_at = ? WHERE id = ?",
        (name, _now(), notebook_id),
    )
    conn.commit()
    changed = cur.rowcount > 0
    conn.close()
    return changed


def share_notebook(notebook_id: str, owner_id: str, email: str, role: str = "editor") -> Dict:
    """Owner grants access to another user by email."""
    conn = _connect()
    own = conn.execute(
        "SELECT 1 FROM notebooks WHERE id = ? AND owner_id = ?", (notebook_id, owner_id)
    ).fetchone()
    if not own:
        conn.close()
        return {"error": "only the owner can share this notebook"}
    email = email.strip().lower()
    conn.execute(
        "INSERT OR REPLACE INTO notebook_shares (notebook_id, email, role, created_at) "
        "VALUES (?, ?, ?, ?)",
        (notebook_id, email, role, _now()),
    )
    conn.commit()
    conn.close()
    return {"email": email, "role": role}


def unshare_notebook(notebook_id: str, owner_id: str, email: str) -> bool:
    conn = _connect()
    own = conn.execute(
        "SELECT 1 FROM notebooks WHERE id = ? AND owner_id = ?", (notebook_id, owner_id)
    ).fetchone()
    if not own:
        conn.close()
        return False
    conn.execute(
        "DELETE FROM notebook_shares WHERE notebook_id = ? AND email = ?",
        (notebook_id, email.strip().lower()),
    )
    conn.commit()
    conn.close()
    return True


def list_collaborators(notebook_id: str) -> List[Dict]:
    conn = _connect()
    rows = conn.execute(
        "SELECT email, role FROM notebook_shares WHERE notebook_id = ? ORDER BY created_at",
        (notebook_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_notebook(notebook_id: str, owner_id: str) -> Optional[Dict]:
    conn = _connect()
    row = conn.execute(
        "SELECT * FROM notebooks WHERE id = ? AND owner_id = ?",
        (notebook_id, owner_id),
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["content"] = json.loads(d["content"])
    return d


def save_notebook(notebook_id: str, owner_id: str, content: Dict, name: Optional[str] = None) -> bool:
    conn = _connect()
    if name is not None:
        cur = conn.execute(
            "UPDATE notebooks SET content = ?, name = ?, updated_at = ? "
            "WHERE id = ? AND owner_id = ?",
            (json.dumps(content), name, _now(), notebook_id, owner_id),
        )
    else:
        cur = conn.execute(
            "UPDATE notebooks SET content = ?, updated_at = ? WHERE id = ? AND owner_id = ?",
            (json.dumps(content), _now(), notebook_id, owner_id),
        )
    conn.commit()
    changed = cur.rowcount > 0
    conn.close()
    return changed


def rename_notebook(notebook_id: str, owner_id: str, name: str) -> bool:
    conn = _connect()
    cur = conn.execute(
        "UPDATE notebooks SET name = ?, updated_at = ? WHERE id = ? AND owner_id = ?",
        (name, _now(), notebook_id, owner_id),
    )
    conn.commit()
    changed = cur.rowcount > 0
    conn.close()
    return changed


def delete_notebook(notebook_id: str, owner_id: str) -> bool:
    conn = _connect()
    cur = conn.execute(
        "DELETE FROM notebooks WHERE id = ? AND owner_id = ?", (notebook_id, owner_id)
    )
    conn.commit()
    changed = cur.rowcount > 0
    conn.close()
    # Best-effort cleanup of the file area.
    try:
        import shutil
        d = notebook_dir(owner_id, notebook_id)
        if d.exists():
            shutil.rmtree(d)
    except Exception:
        pass
    return changed


# --------------------------------------------------------------------------
#  Datasets (filesystem, per notebook)
# --------------------------------------------------------------------------
def notebook_dir(owner_id: str, notebook_id: str) -> Path:
    return FILES_ROOT / owner_id / notebook_id


def _safe_filename(name: str) -> str:
    base = os.path.basename(name).strip().replace("\\", "_")
    base = "".join(c for c in base if c.isalnum() or c in "._- ")
    return base or "file.dat"


def save_dataset(owner_id: str, notebook_id: str, filename: str, file_storage) -> Dict:
    d = notebook_dir(owner_id, notebook_id)
    d.mkdir(parents=True, exist_ok=True)
    safe = _safe_filename(filename)
    dest = d / safe
    file_storage.save(str(dest))
    return {"name": safe, "size": dest.stat().st_size}


def list_datasets(owner_id: str, notebook_id: str) -> List[Dict]:
    d = notebook_dir(owner_id, notebook_id)
    if not d.exists():
        return []
    out = []
    for p in sorted(d.iterdir()):
        if p.is_file():
            out.append({"name": p.name, "size": p.stat().st_size})
    return out


def dataset_path(owner_id: str, notebook_id: str, filename: str) -> Optional[Path]:
    safe = _safe_filename(filename)
    p = notebook_dir(owner_id, notebook_id) / safe
    return p if p.exists() else None


def delete_dataset(owner_id: str, notebook_id: str, filename: str) -> bool:
    p = dataset_path(owner_id, notebook_id, filename)
    if p and p.exists():
        p.unlink()
        return True
    return False


# --------------------------------------------------------------------------
#  Kaggle import
# --------------------------------------------------------------------------
def import_kaggle_dataset(owner_id: str, notebook_id: str, slug: str,
                          username: str = "", key: str = "") -> Dict:
    """Download a Kaggle dataset into the notebook's file area and unzip it.

    *slug* is ``owner/dataset`` (e.g. ``uciml/iris``). Credentials come from the
    arguments, the ``KAGGLE_USERNAME``/``KAGGLE_KEY`` env vars, or ``~/.kaggle/
    kaggle.json``. Requires network access at runtime.
    """
    import base64 as _b64
    import io as _io
    import json as _json
    import urllib.request
    import zipfile

    slug = (slug or "").strip().strip("/")
    if slug.startswith("http"):
        # accept a full kaggle URL too
        import re as _re
        m = _re.search(r"datasets/([^/]+/[^/?#]+)", slug)
        if m:
            slug = m.group(1)
    if "/" not in slug:
        return {"error": "Kaggle dataset must be in the form 'owner/dataset-name'."}

    username = (username or os.getenv("KAGGLE_USERNAME", "")).strip()
    key = (key or os.getenv("KAGGLE_KEY", "")).strip()
    if not username or not key:
        cfg = Path.home() / ".kaggle" / "kaggle.json"
        if cfg.exists():
            try:
                data = _json.loads(cfg.read_text())
                username = username or data.get("username", "")
                key = key or data.get("key", "")
            except Exception:
                pass
    if not username or not key:
        return {"error": "Kaggle credentials required. Provide your Kaggle username "
                         "and API key (from kaggle.com → Account → Create New API Token)."}

    url = f"https://www.kaggle.com/api/v1/datasets/download/{slug}"
    token = _b64.b64encode(f"{username}:{key}".encode()).decode()
    req = urllib.request.Request(url, headers={"Authorization": "Basic " + token})
    dest = notebook_dir(owner_id, notebook_id)
    dest.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            payload = resp.read()
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Kaggle download failed: {exc}. Check the dataset slug and your API key."}

    saved = []
    try:
        zf = zipfile.ZipFile(_io.BytesIO(payload))
        for member in zf.namelist():
            if member.endswith("/"):
                continue
            safe = _safe_filename(member)
            with zf.open(member) as src, open(dest / safe, "wb") as out:
                out.write(src.read())
            saved.append({"name": safe, "size": (dest / safe).stat().st_size})
    except zipfile.BadZipFile:
        # single (already-decompressed) file
        safe = _safe_filename(slug.split("/")[-1] + ".csv")
        (dest / safe).write_bytes(payload)
        saved.append({"name": safe, "size": (dest / safe).stat().st_size})

    return {"status": "imported", "files": saved, "count": len(saved)}
