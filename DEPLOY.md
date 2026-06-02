# Deployment Guide

This app uses **Supabase** for authentication (signup / login / email
verification / password reset) and **Supabase Postgres** for storing user
accounts and notebooks. It deploys on **Render** (free tier works fully).

Full click-by-click instructions are in:

**→ `deploy/SUPABASE_RENDER_STEPS.md`**

---

## The four pieces

1. **Supabase project** — provides Auth API + Postgres database (free).
2. **GitHub repo** — holds the source code for Render to build.
3. **Render web service** — runs the Flask app.
4. **Three environment variables in Render:**
   - `SUPABASE_URL` — your project URL
   - `SUPABASE_ANON_KEY` — public anon key (from Project Settings → API)
   - `DATABASE_URL` — the Postgres pooled connection string

That's the whole setup. No email provider keys, no SMTP — Supabase sends every
auth email from their own infrastructure.

---

## Running locally (development)

```bash
pip install -r requirements.txt
copy .env.example .env       # then edit with your Supabase keys
python app.py
```

If `DATABASE_URL` is blank locally, the app uses a SQLite file in `./data` —
fine for development.

---

## Security note

Notebook code runs inside the server process and `!pip install` affects the
whole server. Fine for yourself, a class, or a trusted team. For untrusted
public users, run each user's kernel in an isolated container.
