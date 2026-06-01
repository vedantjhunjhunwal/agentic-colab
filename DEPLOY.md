# Deployment Guide

This app is set up to deploy on **AWS Educate / AWS Academy Learner Lab** using
EC2 + Docker. Full click-by-click instructions are in:

**→ `deploy/AWS_EDUCATE_STEPS.md`**

---

## Quick overview

The Learner Lab is a sandboxed AWS account (fixed budget, locked to us-east-1,
no App Runner). The reliable deployment is a single EC2 Linux instance running
the app in Docker. Everything builds on Linux in the cloud, so none of the
Windows issues (long paths, DLL errors, spaces in paths) occur.

The flow:

1. **Start Lab** in AWS Academy → open the AWS Console (region: us-east-1).
2. **Launch an EC2 instance** (Amazon Linux 2023, `t3.medium`, open ports 22/80/8080).
3. **Connect** via EC2 Instance Connect (browser terminal — no key file needed).
4. **Install Docker**, clone your code, `docker build`, `docker run` with `-v ~/colab-data:/data`.
5. **Open** `http://YOUR_EC2_PUBLIC_IP` — register and share.

Data lives in `~/colab-data` on the instance and survives lab stop/start
(the instance is stopped, not deleted, when you End Lab).

See `deploy/AWS_EDUCATE_STEPS.md` for every command and the important
budget / public-IP notes.

---

## Environment variables (set via `-e` flags in `docker run`)

| Variable | Required | Description |
|----------|----------|-------------|
| `MAIL_USERNAME` | Yes | Gmail address used to send OTPs |
| `MAIL_PASSWORD` | Yes | 16-char Gmail App Password |
| `COLAB_SECRET` | Yes | Long random string for Flask sessions |
| `ENABLE_2FA` | Yes | `true` to require 2FA on login |
| `COLAB_DATA_DIR` | Yes | `/data` (mounted from `~/colab-data`) |
| `GOOGLE_CLIENT_ID` | Optional | Enables "Sign in with Google" |
| `GOOGLE_CLIENT_SECRET` | Optional | |
| `OAUTH_REDIRECT_BASE` | Optional | Public URL for OAuth redirect |
| `OPENAI_API_KEY` | Optional | LLM for AIDL `generate()` / assistant |

Create a Gmail App Password at https://myaccount.google.com/apppasswords
(requires 2-Step Verification to be enabled).

---

## Running locally (for development)

```bash
pip install -r requirements.txt
copy .env.example .env      # then edit .env with your MAIL_USERNAME / MAIL_PASSWORD
python app.py
```
Open the URL it prints (it auto-picks a free port).

---

## Security note

Notebook code runs inside the server process and `!pip install` affects the
whole server. Fine for yourself, a class, or a trusted team. For untrusted
public users, run each user's kernel in an isolated container.
