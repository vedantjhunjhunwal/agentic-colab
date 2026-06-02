# Deploy Agentic Colab on Render

This build uses Supabase Auth only. No Resend, Brevo, SendGrid, Gmail SMTP, or OTP mailer is required.

## Render env vars

```env
SUPABASE_URL=https://your-project-id.supabase.co
SUPABASE_ANON_KEY=your_anon_public_key
COLAB_SECRET=use-a-long-random-secret
```

## Commands

Build command:
```bash
pip install -r requirements.txt
```

Start command:
```bash
gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 8 --timeout 300 app:app
```
