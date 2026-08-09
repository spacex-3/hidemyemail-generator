<p align="center"><img width=60% src="docs/header.png"></p>

> Automated batch generation of Apple iCloud Hide My Email addresses with a real-time web dashboard.

_Requires an active **iCloud+** subscription._

## ✨ Features

- **Apple ID Login (SRP + 2FA)** — No more manual cookie pasting. Log in directly with your Apple ID and password, complete 2FA on the web dashboard, and sessions are persisted with encrypted password storage (~90-day trust tokens).
- **Multi-Account Support** — Run multiple iCloud accounts simultaneously. Each account has independent controls, progress tracking, and email output files.
- **Web Dashboard** — Real-time UI at `http://localhost:8080` for managing accounts, monitoring generation progress, and downloading results — accessible from any device on your network.
- **Smart Rate-Limit Handling** — Automatic cooldown with configurable intervals (default 45 min, minimum 30 min) + browser fingerprint rotation. Includes 3× retry on transient limits and 5-minute recovery probes after long cooldowns.
- **Per-Account Controls** — Start / Stop / Resume / Restart each account individually, set custom generation targets and cooldown intervals from the dashboard.
- **Persistent Sessions** — Sessions survive server restarts. Passwords are encrypted with a machine-specific key via `cryptography.fernet`.
- **Email History with Timestamps** — All generated emails are saved to `emails-{account}.txt` with generation timestamps, displayed in reverse chronological order on the dashboard.

## 🚀 Quick Start

### Prerequisites

- Python 3.12+
- An active iCloud+ subscription

### 1. Clone & Install

```bash
git clone https://github.com/spacex-3/hidemyemail-generator.git
cd hidemyemail-generator

python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

pip install -r requirements.txt
```

### 2. Start the Dashboard

```bash
python cli.py serve --port 8080
```

### 3. Open the Dashboard

Navigate to **http://localhost:8080** in your browser.

### 4. Add Your Account

1. Click **+ Add Account** on the dashboard
2. Enter your Apple ID and password
3. Complete 2FA verification when prompted (enter the 6-digit code sent to your trusted device)
4. Set your **target** count and **interval** (minutes), then click **▶ Start**

> **Note:** For Chinese mainland Apple IDs, the system automatically uses `icloud.com.cn` endpoints.

## 📖 Usage

### Dashboard Controls

| Control | Description |
|---------|-------------|
| **目标** (Target) | Number of emails to generate in this run |
| **间隔(min)** (Interval) | Cooldown minutes between 5-email cycles (min: 30, default: 45, + 1~3 min random jitter) |
| **▶ Start** | Begin generation with the specified target and interval |
| **⏹ Stop** | Pause the current generation task |
| **▶ Resume** | Continue a stopped task from where it left off |
| **↺ Restart** | Reset progress and start a fresh run with current input values |
| **✕** | Remove account from the dashboard |

### Generation Cycle

```
Generate 2 → 💾 Save to emails-{account}.txt → 3~5s cooldown
Generate 2 → 💾 Save → 3~5s cooldown
...
5 emails done → ⏳ Long cooldown (interval + 1~3 min) → 🔄 Rotate browser fingerprint
→ Next cycle...
```

**On rate limit:**
1. Retry up to 3 times (5s apart) during an active cycle
2. If all retries fail → full long cooldown + fingerprint rotation
3. After cooldown, if still limited → probe every 5 minutes until Apple lifts the block

### CLI Commands

```bash
# Start the web dashboard (default port: 8080)
python cli.py serve --port 8080

# List generated emails for the first account found
python cli.py list
python cli.py list --inactive          # Show inactive emails
python cli.py list --search "label"    # Search by label
```

### Output Files

Generated emails are saved to `emails-{apple_id}.txt` in CSV format:

```
email@icloud.com,2026-04-11 23:01:59
another@icloud.com,2026-04-11 23:02:04
```

## 🐳 Docker / VPS Deployment

If you want to deploy on a VPS, you can run the project directly from the public GHCR image.

### 1. Create `docker-compose.yml`

```yaml
services:
  hme:
    image: ghcr.io/spacex-3/hidemyemail-generator:latest
    container_name: hme
    ports:
      - "8080:8080"
    environment:
      - DATA_DIR=/app/data
    volumes:
      - ./data:/app/data
    restart: unless-stopped
```

### 2. Start the service

```bash
mkdir -p data
docker compose up -d
```

Then open `http://<your-vps-ip>:8080` in your browser.

### 3. Migrate existing generated email history

If you already used the Python version before, you can copy your existing `emails-*.txt` files into the VPS `data/` directory before starting the container:

```bash
mkdir -p data
cp emails-*.txt data/
```

The dashboard will continue loading those historical records after startup, and new generated addresses will append to the same files.

### 4. Re-add accounts after migration

Existing generated email history can be reused directly, but saved login sessions may not remain reusable across machines or containers. After migration, simply log in again from the dashboard. New session files will be stored under `data/sessions/`.

## Mailbox Verification API

The optional `mail` service is a separate sidecar for selling existing HME
addresses with an OpenAI verification-code API. It does **not** modify the HME
generator, Apple session, account scheduler, cooldown, or generated-email
history. It only reads `data/emails-*.txt` to discover aliases.

Before starting it, create a `.env` file next to `docker-compose.yml`:

```bash
MAIL_ADMIN_PASSWORD=replace-with-a-long-random-password
MAIL_PUBLIC_BASE_URL=https://mail.example.com
MAIL_POLL_SECONDS=60
MAIL_COOKIE_SECURE=true
```

`MAIL_PUBLIC_BASE_URL` must be the public HTTPS URL that customers will call.
When running only on a private LAN, use the reachable `http://host:8787` URL
and leave `MAIL_COOKIE_SECURE=false`.

Start or update both services:

```bash
docker compose pull
docker compose up -d
```

Open `http://<server>:8787` and sign in with `MAIL_ADMIN_PASSWORD`.

1. Create an IMAP Profile for the mailbox that Apple forwards HME mail to.
   Gmail, 126 Mail, 163 Mail, and iCloud Mail have built-in IMAP settings, so
   those options require only the mailbox account and provider app password or
   authorization code. Use Custom IMAP for other providers.
2. Select `direct`, `SOCKS5 / SOCKS5h`, or `HTTP CONNECT` for that Profile.
   This affects only IMAP fetching; HME generation remains on the HME
   container's direct network route.
3. Map each Apple source account to its default Profile, then apply an alias
   override only when that HME uses a different forwarding mailbox.
4. Filter the sales table by Apple source account and export state. It is
   paginated at 100 aliases per page. Select unexported aliases and use batch
   issue/export to download `HME----customer-page-url` records; each record is
   marked exported so it cannot be accidentally exported twice.

Existing `emails-{apple-id}.txt` files are imported automatically and remain
unchanged, so addresses generated before this feature was installed can be
configured and sold in the same way as new ones.

Each Profile has a **Recent mail** action in the admin page. It re-scans the
last 20 messages and shows the sender, subject, recipient-routing headers,
OpenAI/code detection result, and matched HME aliases. This is the first place
to check when mail is visible in a provider webmail UI but no code appears on
the customer page. The diagnostic view is admin-only and never shown to a
customer.

The background worker imports new aliases and polls every configured interval.
It stores only strictly routed OpenAI/ChatGPT verification messages, then
purges cached subject, timestamp, and code after the configured retention
period (default: 7 days). A customer request reads this cache and makes one
immediate IMAP refresh when no matching code is cached.

Customer request format:

```bash
curl -H 'Authorization: Bearer CUSTOMER_API_KEY' \
  'https://mail.example.com/api/v1/openai/mailboxes/MAILBOX_ID/latest'
```

The response contains only `subject`, `received_at`, and the six-digit `code`.
It never returns the HME address, Apple account, forwarding mailbox, IMAP
credentials, or message body. A batch export instead gives customers a direct
browser page URL. The page refreshes automatically and shows only the newest
OpenAI code, title, and received time. The URL contains the per-alias secret,
so treat it as the customer's password and do not publish it in a shared log.
The programmatic API also accepts `?key=` for browser integrations, but the
Authorization header is preferred because query strings are commonly retained
in proxy access logs.

Back up the full `data/` directory. In particular, `mailboxes.sqlite3` and
`mailbox-secret.key` must be restored together: the latter encrypts IMAP
passwords and proxy URLs. Do not expose port 8787 directly to the internet
without HTTPS and a reverse proxy; restrict the admin page to yourself.

## 🏗️ Project Structure

```
├── cli.py              # CLI entry point (click)
├── main.py             # Generation engine, progress tracking, account manager
├── server.py           # aiohttp web server + dashboard HTML/JS/CSS
├── icloud/
│   ├── auth.py         # Apple SRP authentication, 2FA, session persistence
│   └── hidemyemail.py  # HideMyEmail API client (generate/reserve/list)
├── sessions/           # Encrypted session data (auto-created, git-ignored)
├── emails-*.txt        # Generated email output files (git-ignored)
└── requirements.txt
```

## 🔒 Security

- Passwords are **never stored in plain text**. They are encrypted using `Fernet` symmetric encryption with a machine-derived key (`PBKDF2-SHA256`, 100k iterations).
- Session trust tokens (~90 days) are used to bypass repeated 2FA.
- The `sessions/` directory and `emails-*.txt` files are excluded from git via `.gitignore`.

## Troubleshooting Authentication

The server automatically follows Apple's `domainToUse` response and selects the
account's `pNNN-maildomainws` partition. If an older saved session reports that
`X-APPLE-WEBAUTH-USER` or the DSID is missing, add the same account again in the
dashboard and complete login/2FA once more. HTTP 401 and 403 responses now stop
the generation task immediately; they are authentication errors, not rate limits.

## 📋 Requirements

```
curl_cffi>=0.7
aiohttp>=3.9
rich==13.7.1
click==8.1.7
certifi==2024.2.2
srp>=1.0.21
requests>=2.31
cryptography>=42.0
```

## License

Licensed under the MIT License - see the [LICENSE file](./LICENSE) for more details.

Maintained in this repository by **[spacex-3](https://github.com/spacex-3)**.
