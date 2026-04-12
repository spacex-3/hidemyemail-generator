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

Originally created by **[rtuna](https://twitter.com/rtunazzz)**. SRP authentication, multi-account dashboard, and smart rate-limit handling by **[spacex-3](https://github.com/spacex-3)**.
