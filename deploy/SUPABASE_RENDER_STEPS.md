# Deploy on Render with Supabase Auth + Database — Step by Step

This app uses **Supabase** for both authentication AND data storage. Supabase
sends the verification + password-reset emails from their own infrastructure,
so there's nothing to configure with Gmail, Brevo, SendGrid, or SMTP.

You'll do four things, in order: set up Supabase, put the code on GitHub,
deploy on Render, and test.

---

## Part 1 — Set up Supabase  · ~5 min

### 1. Create a project
1. Go to https://supabase.com and **Sign up** (use GitHub login — no card).
2. Click **New project**:
   - Name: `agentic-colab`
   - Database password: pick a strong one and **save it** — you'll need it.
   - Region: **Southeast Asia (Singapore)** — closest to India.
   - Plan: Free
3. Click **Create new project** and wait ~1 minute for provisioning.

### 2. Get the auth keys
1. In the project, left sidebar → **Project Settings** (the gear icon) → **API**.
2. Copy two values and paste them somewhere temporary:
   - **Project URL** — looks like `https://abcdefgh.supabase.co`
   - **anon public** key — a long string starting with `eyJ...`

### 3. Get the database connection string
1. Left sidebar → **Project Settings** → **Database** → **Connection string** tab.
2. Choose **URI** format and **Connection pooling** → **Transaction** mode.
3. Copy the string. It looks like:
   ```
   postgresql://postgres.abcdefgh:[YOUR-PASSWORD]@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres
   ```
4. **Replace `[YOUR-PASSWORD]` with the database password from step 1.**

### 4. (Optional but recommended) Allow new sign-ups without email confirmation
By default, Supabase requires users to click an email link before they can log
in. For a class/demo this can be relaxed:
1. Sidebar → **Authentication** → **Providers** → **Email**.
2. Toggle **Confirm email** off (or leave it on if you want the verification).
3. Click **Save**.

You now have three values for Render:
- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`
- `DATABASE_URL` (with your password substituted in)

---

## Part 2 — Put the code on GitHub  · ~5 min

1. Make a free account at https://github.com if you don't have one.
2. Top right **+** → **New repository** → name it `agentic-colab` → **Create**.
3. On the new repo page, click **uploading an existing file**.
4. Drag in **all** files and folders from the unzipped project.
5. Click **Commit changes**.

The `.gitignore` keeps secrets out — your Supabase keys go in Render only.

---

## Part 3 — Deploy on Render  · ~10 min

1. Sign up at https://render.com — choose **Sign in with GitHub**.
2. Dashboard → **New** → **Blueprint**.
3. Select your `agentic-colab` repo → **Connect**.
4. Render reads `render.yaml` and prompts for the secret values. Paste:

   | Key | Value |
   |---|---|
   | `SUPABASE_URL` | `https://abcdefgh.supabase.co` |
   | `SUPABASE_ANON_KEY` | the long `eyJ...` anon key |
   | `DATABASE_URL` | the full Postgres URI (with password substituted) |
   | `SUPABASE_PASSWORD_REDIRECT` | leave blank for now |

5. Click **Apply**. Render builds the app (3–6 minutes).
6. When live, your URL appears at the top, like `https://agentic-colab.onrender.com`.

### After first deploy — set the password-reset redirect
1. Copy your Render URL.
2. Render → your service → **Environment** → set `SUPABASE_PASSWORD_REDIRECT` to:
   ```
   https://YOUR-APP.onrender.com/login
   ```
3. Supabase → **Authentication** → **URL Configuration** → add the same URL
   under **Redirect URLs**, click **Save**.

---

## Part 4 — Test  · ~2 min

1. Open `https://YOUR-APP.onrender.com`.
2. Click **Create an account**, enter name, email, password (8+ chars).
3. You're logged in immediately. (If you left "Confirm email" on in Supabase,
   you also get a verification email from Supabase — click the link to verify.)
4. Create a notebook, run `print("hello")` in a Python cell.
5. **Confirm persistence:** in Render click **Manual Deploy → Deploy latest commit**.
   When it's done, log back in — your account and notebook are still there
   (they live in Supabase Postgres, not on Render's disk).

---

## How you'll know it worked (Render Logs)

After deploy, the **Logs** tab should show:
```
[env] SUPABASE_URL found     : True
[env] SUPABASE_ANON_KEY found: True
================================================================
 [AUTH] ENABLED — Supabase email/password authentication
        url https://abcdefgh.supabase.co
================================================================
```

If `SUPABASE_URL found: False`, the env var isn't set or has a typo.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| "Supabase is not configured" | `SUPABASE_URL` or `SUPABASE_ANON_KEY` missing in Render Environment. |
| "Invalid login credentials" | Wrong password, OR you have "Confirm email" enabled and haven't clicked the verification link yet. |
| "Email already registered" | Use **Sign in** instead, or use Forgot password. |
| Notebooks disappear after redeploy | `DATABASE_URL` is missing or wrong — without it, data goes to ephemeral SQLite. |
| Build fails on `psycopg2-binary` | Render free tier supports it via wheel — should always work. If it doesn't, check Render's Python runtime version. |
| Verification email never arrives | Check Supabase dashboard → **Authentication → Logs**. Supabase has rate limits (~3 emails/hour per address) on free tier. |
| Reset password email link goes to localhost | Set `SUPABASE_PASSWORD_REDIRECT` (see Part 3 above) and add it to Supabase Redirect URLs. |

---

## What you removed compared to the old setup

- **No more OTP system** — Supabase handles email verification natively.
- **No more Brevo / SendGrid / Resend / Gmail SMTP** — Supabase sends its own
  emails from a fully-authenticated infrastructure.
- **No more separate Neon database** — Supabase Postgres serves the same role.

Your secrets in Render: just `SUPABASE_URL`, `SUPABASE_ANON_KEY`, and
`DATABASE_URL`. That's the whole config.
