# Agentic Colab

A Google Colab–faithful notebook environment with:
- **Python** cells (full pandas/numpy/matplotlib/sklearn runtime)
- **AIDL v2** cells — a Python-like AI workflow language with `load()`, `classifier()`, `regressor()` builtins
- Persistent notebooks, cell outputs, and uploaded datasets (per-user SQLite + filesystem)
- Google OAuth sign-in **or** demo login
- Agentic assistant that explains errors — **no API key required** (add OpenAI/Gemini for LLM mode)
- Deployable on **AWS Educate / AWS Academy Learner Lab** with EC2 + Docker (see `DEPLOY.md` and `deploy/AWS_EDUCATE_STEPS.md`)

---

## Quick start (local)

```bash
pip install -r requirements.txt
python app.py
# Open http://localhost:8080
```

---

## Docker Compose

```bash
docker compose up --build
# Open http://localhost:8080
```

---

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `GOOGLE_CLIENT_ID` | — | Enables "Sign in with Google" |
| `GOOGLE_CLIENT_SECRET` | — | Required alongside client ID |
| `COLAB_SECRET` | auto | Flask session secret (set for stability across restarts) |
| `COLAB_DATA_DIR` | `./data` | Where notebooks and datasets are stored |
| `PORT` | `8080` | HTTP port |
| `AGENT_LLM_PROVIDER` | — | `openai` or `gemini` for server-side LLM |
| `OPENAI_API_KEY` | — | Used when provider is `openai` |
| `GOOGLE_API_KEY` | — | Used when provider is `gemini` |

Copy `.env.example` → `.env` and fill in values, then load with:
```bash
export $(cat .env | grep -v ^# | xargs)
python app.py
```

---

## Google OAuth setup

1. Go to [Google Cloud Console → APIs & Services → Credentials](https://console.cloud.google.com/apis/credentials)
2. Create an OAuth 2.0 Client ID (Web application)
3. Add `http://localhost:8080/auth/google/callback` as an authorised redirect URI (add your production URL too)
4. Copy the Client ID and Secret into your env vars
5. The "Sign in with Google" button will appear automatically

---

## Deploy on AWS Educate / AWS Academy Learner Lab

Deploy on a single EC2 instance with Docker. Full click-by-click guide:
**`deploy/AWS_EDUCATE_STEPS.md`**.

```bash
# On the EC2 instance (Amazon Linux 2023), after installing Docker:
git clone https://github.com/YOUR_USERNAME/agentic-colab.git
cd agentic-colab
docker build -t agentic-colab .
mkdir -p ~/colab-data
docker run -d --name agentic-colab --restart unless-stopped \
  -p 80:8080 -v ~/colab-data:/data \
  -e COLAB_DATA_DIR=/data -e MPLBACKEND=Agg -e ENABLE_2FA=true \
  -e COLAB_SECRET="a-long-random-string" \
  -e MAIL_USERNAME="you@gmail.com" -e MAIL_PASSWORD="your16charapppassword" \
  agentic-colab
```

Then open `http://YOUR_EC2_PUBLIC_IP`. Data persists in `~/colab-data` across
lab stop/start. See the guide for the budget and public-IP notes.

---

## AIDL language quick reference

```
# Load a dataset
data = load("file.csv")

# Train a classifier or regressor
model = classifier()            # infers target column
model = regressor()
result = model.train(data, epochs=20)
print("accuracy", model.accuracy)

# Predict
pred = model.predict(data, row=0)

# Dataset attributes
print(data.rows, data.cols)
print(data.describe())

# Python-like control flow
for x in range(10):
    if x % 2 == 0:
        print(x, "is even")

# Functions
def square(n):
    return n * n

print(square(7))
```

Open the **AIDL syntax manual** (book icon in the toolbar) for the full reference.

---

## Architecture

```
app.py          Flask routes and API
aidl/           AIDL v2 language (lexer, parser, AST, interpreter)
kernel.py       Per-notebook Python + AIDL kernels (in-memory state)
agent.py        Deterministic error explainer + optional LLM chat
storage.py      SQLite (notebooks) + filesystem (datasets)
auth.py         Google OAuth + demo login
manual.py       AIDL syntax manual markdown
templates/      Jinja2 HTML (login, dashboard, notebook)
static/css/     colab.css — Colab-faithful theme
static/js/      markdown.js, highlight.js, dashboard.js, notebook.js
deploy/         AWS_EDUCATE_STEPS.md (deployment guide)
```
