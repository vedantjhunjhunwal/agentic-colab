# Deploy Agentic Colab on Render Free

This project is ready to deploy on Render as a free Python Web Service.

Render will give a public HTTPS URL like:

```text
https://agentic-colab.onrender.com
```

> Note: Render free services may sleep after inactivity. The first request after sleep can take 30–60 seconds.

---

## 1. Push the project to GitHub

```bash
git add .
git commit -m "Prepare Agentic Colab for Render deployment"
git push
```

---

## 2. Create a Render Web Service

1. Go to Render.
2. Sign in with GitHub.
3. Click **New +**.
4. Select **Web Service**.
5. Connect your GitHub repository.
6. Select the branch: `main`.

---

## 3. Render settings

Use these exact settings if Render asks manually:

```text
Name: agentic-colab
Runtime: Python 3
Plan: Free
Build Command: pip install --upgrade pip && pip install -r requirements.txt
Start Command: gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 8 --timeout 300 app:app
Health Check Path: /healthz
```

Environment variables:

```text
COLAB_DATA_DIR=/tmp/agentic-colab-data
MPLBACKEND=Agg
ENABLE_2FA=false
COLAB_SECRET=<any long random string>
```

Optional LLM variables:

```text
AGENT_LLM_PROVIDER=openai
OPENAI_API_KEY=<your key>
```

or:

```text
AGENT_LLM_PROVIDER=gemini
GOOGLE_API_KEY=<your key>
```

Do not put API keys in GitHub.

---

## 4. Blueprint deploy option

This repo includes `render.yaml`, so you can also deploy as a Render Blueprint:

1. Render Dashboard → **New +** → **Blueprint**.
2. Select this GitHub repo.
3. Render reads `render.yaml` automatically.
4. Click **Apply**.

---

## 5. Test after deployment

Open the Render URL.

Use demo login from the UI.

Try an AIDL cell:

```python
data = load("customers.csv")
print("rows", data.rows, "cols", data.cols)
model = classifier()
model.train(data, epochs=10)
print("accuracy", round(model.accuracy, 4))
for i in range(3):
    print("row", i, "prediction", model.predict(data, row=i))
```

---

## 6. Important limitation on Render Free

Render Free has an ephemeral filesystem. This means notebooks and uploaded files may not be permanent across restarts or redeploys.

For a recruiter demo, this is acceptable if you also keep:

- GitHub README
- Screenshots
- Demo video
- Sample notebooks / sample AIDL code

For permanent storage, upgrade Render and attach a persistent disk, or use an external database/object store.

