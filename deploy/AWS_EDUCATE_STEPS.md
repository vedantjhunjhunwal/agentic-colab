# Deploy on AWS Educate / AWS Academy Learner Lab

The AWS Academy **Learner Lab** is a sandboxed AWS account with a fixed budget and
some restrictions (no App Runner, no creating IAM roles, locked to **us-east-1**).
The reliable way to deploy here is **EC2 + Docker** — a Linux server you control.

Because everything builds and runs on Linux in the cloud, none of the Windows
problems (long paths, DLL errors, spaces) can happen.

You do everything through the **web console** — no AWS CLI needed.

---

## Step 1 — Start the lab

1. Log in to **AWS Academy** → your course → **Modules → Learner Lab**.
2. Click **Start Lab**. Wait until the dot next to "AWS" turns **green**.
3. Click the **AWS** button at the top — this opens the AWS Console.

> Important: confirm the region (top-right of the console) is
> **N. Virginia (us-east-1)**. Learner Labs only work in this region.

---

## Step 2 — Launch an EC2 instance

1. In the console search bar type **EC2** → open it.
2. Click **Launch instance**.
3. Fill in:
   - **Name:** `agentic-colab`
   - **Application and OS Image (AMI):** **Amazon Linux 2023** (the default, free-tier eligible)
   - **Instance type:** `t3.medium` (2 vCPU, 4 GB — enough for Flask + ML).
     If `t3.medium` is blocked, use `t2.medium`.
   - **Key pair:** choose **vockey** (the lab provides this automatically).
     *(If `vockey` isn't listed, click "Create new key pair", name it `colab-key`,
     download the `.pem`, and keep it.)*
   - **Network settings →** click **Edit**, then under **Firewall (security groups)**
     → **Create security group** and add these inbound rules:

     | Type | Port | Source |
     |------|------|--------|
     | SSH | 22 | Anywhere (0.0.0.0/0) |
     | HTTP | 80 | Anywhere (0.0.0.0/0) |
     | Custom TCP | 8080 | Anywhere (0.0.0.0/0) |

   - **Configure storage:** change to **20 GiB** (torch/tensorflow need space).
4. Click **Launch instance**, then **View all instances**.
5. Wait until **Instance state** = "Running" and **Status check** = "2/2 checks passed".

---

## Step 3 — Connect to the instance (browser terminal)

1. Select your instance → click **Connect** (top button).
2. Choose the **EC2 Instance Connect** tab → click **Connect**.
3. A terminal opens in your browser. (This avoids dealing with the `.pem` key file.)

---

## Step 4 — Install Docker

Paste these into the browser terminal, one block at a time:
```bash
sudo yum update -y
sudo yum install -y docker git
sudo systemctl start docker
sudo systemctl enable docker
sudo usermod -aG docker ec2-user
```
Then refresh your shell so Docker works without sudo:
```bash
newgrp docker
docker --version
```

---

## Step 5 — Get your code onto the server

**Easiest — from GitHub:**
First, upload your project folder to a GitHub repo (the `.gitignore` keeps your
`.env` and database out of GitHub). Then on the EC2 terminal:
```bash
git clone https://github.com/YOUR_USERNAME/agentic-colab.git
cd agentic-colab
```

**Alternative — upload from your laptop** (only if you created your own key in Step 2).
Run this in a local PowerShell (not the browser terminal), then continue on EC2:
```bash
scp -i colab-key.pem -r "C:\Users\Vedant Jhunjhunwala\Downloads\agentic-colab" ec2-user@YOUR_PUBLIC_IP:~
```

---

## Step 6 — Build and run the app

On the EC2 terminal, inside the `agentic-colab` folder:
```bash
# Build the image (on Linux — no Windows issues)
docker build -t agentic-colab .

# Folder for persistent data (notebooks, uploads, database) on the instance disk
mkdir -p ~/colab-data

# Run the container
docker run -d \
  --name agentic-colab \
  --restart unless-stopped \
  -p 80:8080 \
  -v ~/colab-data:/data \
  -e COLAB_DATA_DIR=/data \
  -e MPLBACKEND=Agg \
  -e ENABLE_2FA=true \
  -e COLAB_SECRET="change-me-to-a-long-random-string" \
  -e MAIL_USERNAME="youraddress@gmail.com" \
  -e MAIL_PASSWORD="your16charapppassword" \
  agentic-colab
```
Check it started:
```bash
docker logs agentic-colab
```
You should see the startup banner and `[MAIL] ENABLED`.

---

## Step 7 — Open your app

1. In the EC2 console, select your instance and copy its **Public IPv4 address**.
2. In your browser, go to:
   ```
   http://YOUR_PUBLIC_IP
   ```
3. Register an account — the OTP arrives at the email you sign up with.

Share that `http://YOUR_PUBLIC_IP` link with anyone; they only need a browser.

---

## IMPORTANT — Learner Lab behaviour (read this)

- **Budget:** the lab has a limited credit budget (often ~$50–100). A running
  `t3.medium` costs ~$0.04/hour. **Stop the lab when you're not using it.**
- **Ending a session:** click **End Lab** in AWS Academy. Your instance is
  **stopped** (not deleted) — your data in `~/colab-data` is safe.
- **Next session:** click **Start Lab** again. The instance **auto-starts**, and
  because of `--restart unless-stopped`, your app comes back up automatically.
  **But the Public IP changes each time** — copy the new IP from the EC2 console.
- **Session time limit:** labs auto-stop after a few hours; just start again.
- If you used Google sign-in, the changing IP breaks the OAuth redirect each
  session. For a stable address, ask your instructor whether **Elastic IP** is
  allowed in your lab, or stick to email/password login (works regardless of IP).

---

## Updating the app later
On the EC2 terminal:
```bash
cd ~/agentic-colab
git pull                              # if you used GitHub
docker build -t agentic-colab .
docker stop agentic-colab && docker rm agentic-colab
docker run -d --name agentic-colab --restart unless-stopped \
  -p 80:8080 -v ~/colab-data:/data \
  -e COLAB_DATA_DIR=/data -e MPLBACKEND=Agg -e ENABLE_2FA=true \
  -e COLAB_SECRET="..." -e MAIL_USERNAME="..." -e MAIL_PASSWORD="..." \
  agentic-colab
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Page won't load | Check the security group has port **80** open to 0.0.0.0/0. |
| `docker: permission denied` | Run `newgrp docker` (or log out and reconnect). |
| Mail not sending | `docker logs agentic-colab` — look for the `[MAIL]` line; check your Gmail App Password. |
| Instance won't start next session | Budget may be exhausted — check the lab's credit usage. |
| Container not running | `docker ps -a`, then `docker logs agentic-colab` to see the error. |
