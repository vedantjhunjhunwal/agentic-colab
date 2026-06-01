# Deploy on Render — Step by Step

Render builds your `Dockerfile` in the cloud and gives you an HTTPS URL.
Mail/OTP, registration, 2FA, password reset, and notebooks all work.
No Docker on your laptop, no Windows issues.

There are two ways: the **Blueprint** (uses the included `render.yaml`, easiest)
or a **manual Web Service**. Both are below — pick one.

---

## Step 1 — Get a Gmail App Password (for OTP email)

1. Turn on 2-Step Verification: https://myaccount.google.com/security
2. Create an App Password: https://myaccount.google.com/apppasswords
   - App: **Mail**, Device: **Other** → name it "Agentic Colab" → **Generate**.
3. Copy the 16-character password (spaces are fine — the app strips them).
   You'll paste this as `MAIL_PASSWORD` in Render.

> Use the App Password, NOT your normal Gmail password — Gmail will reject the latter.

---

## Step 2 — Put the code on GitHub

1. Create a free account at https://github.com and make a new repository.
2. Upload the whole project folder (including `render.yaml` and `Dockerfile`).
   - On the repo page: **Add file → Upload files** → drag everything in → **Commit**.
   - The `.gitignore` keeps your `.env` and database OUT of GitHub (good — secrets
     go in Render's dashboard instead).

---

## Step 3a — Deploy with the Blueprint (recommended)

1. Sign up at https://render.com (log in with GitHub).
2. Click **New → Blueprint**.
3. Select your `agentic-colab` repository. Render detects `render.yaml`.
4. Render shows the service it will create and **prompts for the secret values**:
   - `MAIL_USERNAME` → your Gmail address (e.g. `you@gmail.com`)
   - `MAIL_PASSWORD` → the 16-char App Password from Step 1
   - `DATABASE_URL` → your Neon connection string (set up Neon first — see the
     **Database** section below; or leave it blank now and add it in the dashboard
     right after, before you create accounts you want to keep)
   - `OAUTH_REDIRECT_BASE`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` →
     leave blank unless you're using Google sign-in
5. Click **Apply** / **Create**. Render builds the image (3–6 min) and deploys.
6. When it's live, your URL appears at the top, like:
   `https://agentic-colab.onrender.com`

Skip to **Step 4**.

---

## Step 3b — Deploy as a manual Web Service (alternative)

1. Render dashboard → **New → Web Service** → connect your repo.
2. Settings:
   - **Language / Runtime:** Docker (auto-detected from `Dockerfile`)
   - **Region:** Singapore (closest to India)
   - **Instance type:** Free
3. Under **Environment**, add these variables:

   | Key | Value |
   |-----|-------|
   | `MPLBACKEND` | `Agg` |
   | `COLAB_DATA_DIR` | `/data` |
   | `ENABLE_2FA` | `true` |
   | `MAIL_SERVER` | `smtp.gmail.com` |
   | `MAIL_PORT` | `587` |
   | `MAIL_USE_TLS` | `true` |
   | `MAIL_USERNAME` | your Gmail address |
   | `MAIL_PASSWORD` | your 16-char App Password |
   | `COLAB_SECRET` | any long random string |
   | `DATABASE_URL` | your Postgres connection string (see Database section) |

   For `DATABASE_URL`: in Render, **New → PostgreSQL** (free), then copy its
   **Internal Connection String** into this variable. Without it, the app uses a
   local file that resets on restart.

4. Click **Create Web Service**. Render builds and deploys.

---

## Step 4 — Test it

1. Open your `https://...onrender.com` URL.
2. Click **Create an account**, enter a name, email, and password.
3. You should receive a 6-digit OTP **by email** within a few seconds.
   Enter it → your account is created and you're logged in.
4. Try a notebook: run `print("hello")` in a Python cell, and an AIDL cell too.

If the OTP email doesn't arrive, see Troubleshooting below.

---

## Step 5 — (Only if using Google sign-in)

1. After the first deploy, copy your Render URL.
2. Set `OAUTH_REDIRECT_BASE` to that URL in Render → **Environment**.
3. In https://console.cloud.google.com/apis/credentials → your OAuth client →
   **Authorised redirect URIs**, add:
   `https://YOUR-APP.onrender.com/auth/google/callback`
4. Save → Render redeploys automatically.

---

## Database — set up Neon (permanent free storage)

Your notebooks and user accounts are stored in an external PostgreSQL database so
they persist no matter what the free web service does. We use **Neon** — a
permanently free Postgres (no credit card, doesn't expire). Do this once:

### 1. Create a Neon database
1. Go to https://neon.tech and **Sign up** (log in with Google or GitHub — no card).
2. Click **Create project** (or use the one Neon makes automatically):
   - **Name:** `agentic-colab`
   - **Postgres version:** leave default
   - **Region:** **AWS Asia Pacific (Singapore)** — matches Render's Singapore
     region for low latency (pick the closest to you if Singapore isn't ideal).
3. Click **Create**. Neon creates a database called `neondb`.

### 2. Copy the connection string
1. On your project's dashboard, find **Connection Details** (or click **Connect**).
2. Turn **Connection pooling** **ON** (recommended — handles many connections).
3. Copy the full connection string. It looks like:
   ```
   postgresql://neondb_owner:AbC123XyZ@ep-cool-name-12345-pooler.ap-southeast-1.aws.neon.tech/neondb?sslmode=require
   ```
   Keep it private — it contains a password. (Don't paste it into any file you
   commit to GitHub; it only goes in the Render dashboard below.)

### 3. Give it to Render
1. Render dashboard → your **agentic-colab** web service → **Environment** tab.
2. Click **Add Environment Variable** (or edit `DATABASE_URL` if it already exists):
   - **Key:** `DATABASE_URL`
   - **Value:** paste the Neon connection string from step 2.
3. Click **Save Changes**. Render redeploys automatically.

That's it — on restart the app connects to Neon, creates its tables on first run,
and all users and notebooks persist permanently. You can confirm in Render's
**Logs**: there's no SQLite fallback message, and registration/login work.

> The included `render.yaml` is already set up for this: `DATABASE_URL` is
> dashboard-managed (`sync: false`) and there is no Render database block, so
> your Neon value is never overwritten.

> Neon's free tier auto-suspends the database after ~5 minutes idle and wakes it
> on the next query (a 1–2 second delay). This is normal and costs nothing.

If you run locally with no `DATABASE_URL`, the app uses a SQLite file in `./data`
automatically — no setup needed for development.

---

## Important notes about Render's free tier

- **Your notebooks and accounts persist** in Neon (above) — safe across restarts
  and redeploys, even on the free web tier.
- **Sleeps when idle:** after 15 minutes of no traffic, the free web service spins
  down. The next visit wakes it (a 30–60 second cold start). For an always-on
  app, upgrade to the **Starter** plan ($7/month).
- **Uploaded dataset files** (CSVs uploaded into a notebook's Files panel) sit on
  the web service's disk, which is still ephemeral on free tier — those files
  reset on restart. Your notebooks, code, saved outputs, and accounts (in Neon)
  are NOT affected. To persist uploaded files too, add a disk (set
  `plan: starter` and uncomment the `disk:` block in `render.yaml`).

---

## Updating the app later

Because `autoDeploy` is on, just push to GitHub and Render rebuilds and
redeploys automatically. Or click **Manual Deploy → Deploy latest commit**.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| OTP email never arrives | Check Render **Logs** for the `[MAIL]` line. `[MAIL] ENABLED` means it sent — check spam. `[MAIL] DISABLED` means `MAIL_USERNAME`/`MAIL_PASSWORD` aren't set. |
| "credentials were rejected" in logs | You used your normal Gmail password — generate an **App Password** instead and update `MAIL_PASSWORD`. |
| Mail times out | Rare on Render, but try `MAIL_PORT=465` and `MAIL_USE_SSL=true` (and `MAIL_USE_TLS=false`). |
| App shows "Application failed to respond" | Check Logs; usually a build error. The app binds Render's `PORT` automatically, so don't set a `PORT` variable yourself. |
| Slow first load | Free tier cold start — normal. Upgrade to Starter to stay always-on. |
| Lost my notebooks after a redeploy | Free tier resets data; add a disk (see "Important notes" above). |
