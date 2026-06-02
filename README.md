# Agentic AI DSL Colab

Google-Colab-style notebook for Python and AIDL with Supabase-only authentication.

## Required Render environment variables

```env
SUPABASE_URL=https://your-project-id.supabase.co
SUPABASE_ANON_KEY=your_anon_public_key
COLAB_SECRET=use-a-long-random-secret
```

Email providers such as Resend, Brevo, SendGrid, and SMTP mailers have been removed. Registration and login use Supabase Auth only.
