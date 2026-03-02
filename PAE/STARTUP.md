# PAE Startup Guide

End-to-end walkthrough from zero to first trade signal.

---

## How files get to where they need to be

```
Your Windows PC  ──git push──▶  GitHub  ──git clone──▶  Mac Mini
                                                           (all code)

Your Windows PC  ──FileZilla──▶  Mac Mini
                                   .env  (credentials — never on GitHub)
```

**Rule of thumb:**
- Code → GitHub → Mac Mini via `git clone` / `git pull`
- Credential files → FileZilla directly onto the Mac Mini

---

## Part 1 — Accounts to create first (do these before touching the Mac Mini)

### 1.1 Alpaca (broker)

1. Go to [alpaca.markets](https://alpaca.markets) and sign up
2. Verify your email
3. In the dashboard, switch to **Paper Trading** (toggle at top-right)
4. Go to **API Keys** → **Generate New Key**
5. Copy both values — you only see the secret once:
   - `ALPACA_API_KEY`  looks like `PKXXXXXXXXXXXXXXXXXX`
   - `ALPACA_SECRET_KEY`  looks like a 40-char alphanumeric string
6. Save them in your password manager right now

> You do **not** need to fund the account.  Paper trading uses fake money.

### 1.2 Telegram bot

1. Open Telegram on your phone or desktop
2. Search for `@BotFather` and start a chat
3. Send: `/newbot`
4. Follow the prompts — choose any name and a username ending in `bot`
5. BotFather replies with a token like:
   `1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ`
   → This is your `TELEGRAM_BOT_TOKEN`
6. Send any message to your new bot (just type "hello")
7. In a browser go to:
   `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
   (replace `<YOUR_TOKEN>` with the actual token)
8. In the JSON response find `"chat":{"id":XXXXXXXXX}` — that number is your
   `TELEGRAM_CHAT_ID`

### 1.3 Anthropic API (Claude — optional but recommended)

Claude is the fallback LLM and handles exit-signal analysis.
If you skip this, Ollama handles everything but exit signals will degrade.

1. Go to [console.anthropic.com](https://console.anthropic.com)
2. Sign up / log in
3. Go to **API Keys** → **Create Key**
4. Copy the key: `sk-ant-XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX`
   → This is your `ANTHROPIC_API_KEY`
5. Add a small amount of credit ($5–10 is plenty for testing)

---

## Part 2 — Web hosting MySQL setup

Do this from your hosting control panel (cPanel / phpMyAdmin).

### 2.1 Create the database and user

> **GreenGeeks note:** cPanel automatically prefixes every database name and
> username with your cPanel account name (`alexmane_`).  You cannot change
> this — it's enforced by the host.  The names below already include the prefix.

In cPanel → **MySQL Databases**, create:
- Database: `alexmane_pae_core`
- User: `alexmane_pae_user` with a strong password
- Then use **Add User to Database** to grant the user **ALL PRIVILEGES** on `alexmane_pae_core`

You do not need to run raw SQL for this — cPanel's UI handles it.
If you prefer phpMyAdmin, the equivalent SQL is:

```sql
-- (already handled by cPanel UI — only run this if doing it manually)
GRANT ALL PRIVILEGES ON alexmane_pae_core.* TO 'alexmane_pae_user'@'%';
FLUSH PRIVILEGES;
```

> Write down the password — you will need it in your `.env` file.

### 2.2 Allow remote connections

In cPanel → **Remote MySQL**:

1. Add your Mac Mini's public IP address
   (find it at [whatismyip.com](https://whatismyip.com) while on the Mac Mini's network)
2. Save

### 2.3 Your connection details

| Field | Value |
|-------|-------|
| Host | `chi206.greengeeks.net` |
| Port | `3306` |
| Database | `alexmane_pae_core` |
| User | `alexmane_pae_user` |
| Password | whatever you set in cPanel |

Your `DATABASE_URL` will be:
```
mysql+pymysql://alexmane_pae_user:YOUR_PASSWORD@chi206.greengeeks.net:3306/alexmane_pae_core
```

---

## Part 3 — Mac Mini setup

Everything below runs on the Mac Mini.

### 3.1 Install Homebrew (if not installed)

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

### 3.2 Install Python 3.11

```bash
brew install python@3.11
python3.11 --version   # should print Python 3.11.x
```

### 3.3 Ollama on the Mac Mini

Ollama is already installed and the model is present — skip the download.
Just make sure it's running:

```bash
brew services start ollama
ollama list   # should show hf.co/unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF:Q3_K_M
```

### 3.3a Windows GPU as primary Ollama (optional but faster)

PAE supports a two-endpoint Ollama setup: **Windows GPU → Mac Mini → Claude**.
To enable this, do the following on your **Windows 11 PC**:

**1. Install Ollama for Windows** (if not already):
Download from [ollama.com](https://ollama.com) and install.

**2. Expose Ollama on the local network:**

Open Windows → Search → **Edit the system environment variables** → **Environment Variables** → **New** (System variables):
- Variable name: `OLLAMA_HOST`
- Variable value: `0.0.0.0:11434`

Restart Ollama after setting this.

**3. Allow port 11434 through Windows Firewall:**

Run in PowerShell (as Administrator):
```powershell
New-NetFirewallRule -DisplayName "Ollama LAN" -Direction Inbound -Protocol TCP -LocalPort 11434 -Action Allow
```

**4. Find your Windows PC's local IP:**
```powershell
ipconfig
# Look for IPv4 Address under your active adapter, e.g. 192.168.1.100
```

**5. Add to `.env` on the Mac Mini:**
```dotenv
OLLAMA_BASE_URL=http://192.168.1.100:11434    # Windows GPU (primary)
OLLAMA_FALLBACK_URL=http://localhost:11434     # Mac Mini (fallback)
```

PAE will now use the Windows GPU for inference and automatically fall back to
the Mac Mini if the Windows machine is off or unreachable.

### 3.4 Clone the repo

```bash
cd ~
git clone https://github.com/YOUR_USERNAME/PAE.git
cd PAE
```

### 3.5 Create the virtualenv and install dependencies

```bash
python3.11 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

---

## Part 4 — Create the credentials file (FileZilla upload)

### 4.1 Create `.env` on your Windows PC first

On your Windows PC, open a text editor and create a file called `.env`
(no extension, just `.env`).  Use the template below, filling in every
`REPLACE_ME` value with the real credentials you collected in Part 1 and 2.

```dotenv
# ── Database ──────────────────────────────────────────────────────────────────
DATABASE_URL=mysql+pymysql://alexmane_pae_user:REPLACE_ME@chi206.greengeeks.net:3306/alexmane_pae_core

# ── LLM — Ollama (running locally on Mac Mini) ───────────────────────────────
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen3-coder:30b

# ── LLM — Claude (fallback / exit-signal analysis) ───────────────────────────
ANTHROPIC_API_KEY=sk-ant-REPLACE_ME
CLAUDE_MODEL=claude-sonnet-4-6

# ── Alpaca paper trading ──────────────────────────────────────────────────────
ALPACA_API_KEY=PKXXXXXXXXXXXXXXXXXX
ALPACA_SECRET_KEY=REPLACE_ME

# ── Telegram ──────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN=REPLACE_ME
TELEGRAM_CHAT_ID=REPLACE_ME

# ── Safety: start with both true, flip to false when ready ───────────────────
DRY_RUN=true
PAPER_TRADING=true

# ── Scheduler ─────────────────────────────────────────────────────────────────
CHECK_INTERVAL_MINUTES=60

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_LEVEL=INFO
```

> **This file MUST NOT be committed to GitHub.**
> Upload it only via FileZilla as described next.

### 4.2 Upload `.env` via FileZilla

1. Open FileZilla
2. Connect to your Mac Mini via **SFTP**:
   - Host: Mac Mini's local IP or hostname (find in System Preferences → Sharing)
   - Port: `22`
   - Protocol: `SFTP – SSH File Transfer Protocol`
   - User / Password: your Mac Mini login credentials
3. In the right-hand (remote) panel, navigate to `/Users/YOUR_MAC_USERNAME/PAE/`
4. Drag your `.env` file from the left-hand (local) panel into that folder
5. Confirm the upload

---

## Part 5 — Initialise the database and register the strategy

Back on the Mac Mini terminal:

### 5.1 Test the database connection

```bash
cd ~/PAE
source venv/bin/activate

python -c "
from app.core.database import engine
with engine.connect() as c:
    print('Database connection OK')
"
```

If this fails, double-check:
- The `DATABASE_URL` in `.env`
- That your Mac Mini's IP is whitelisted in cPanel Remote MySQL

### 5.2 Create all tables

```bash
python -c "from app.core.database import init_db; init_db(); print('Tables created')"
```

### 5.3 Register the propaganda-arbitrage strategy

```bash
python -c "
from app.core.database import db_session
from app.core.strategy_loader import StrategyLoader
from app.models import Strategy

with db_session() as db:
    StrategyLoader().register_strategy(db, 'propaganda-arbitrage')
    s = db.query(Strategy).filter_by(name='propaganda-arbitrage').first()
    s.is_active = True
    db.commit()
    print(f'Strategy registered: id={s.id}, active={s.is_active}')
"
```

---

## Part 6 — System health check

```bash
python -c "
from app.workers.health import check_system_health
import json
print(json.dumps(check_system_health(), indent=2))
"
```

Expected output:

```json
{
  "overall": "healthy",
  "database": "ok",
  "ollama": "ok",
  "broker": "ok",
  "telegram": "ok",
  "details": {}
}
```

**If something shows as `unavailable` or `degraded`:**

| Component | What to check |
|-----------|--------------|
| `database` | `DATABASE_URL` in `.env`, cPanel Remote MySQL whitelist |
| `ollama` | `brew services list` — is ollama running? `ollama list` — is the model there? |
| `broker` | `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` in `.env`, switched to paper account? |
| `telegram` | `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env` |

---

## Part 7 — First dry run (no orders, no DB writes)

Run the workers for one cycle with `DRY_RUN=true` (already set):

```bash
# Terminal 1
python scripts/run_workers.py
```

```bash
# Terminal 2 (separate window)
python scripts/run_telegram_bot.py
```

Watch the logs in Terminal 1.  After ~60 seconds you should see:

```
INFO  scrape_news — starting, active_strategies=1
INFO  RssScraper — fetched 8 articles from Reuters Business
INFO  ArticleProcessor — 6 new, 2 duplicates skipped
INFO  PatternDetector — 1 coverage gap detected for NVDA
INFO  LLMSynthesizer — generating thesis for NVDA via Ollama...
INFO  TelegramNotifier — opportunity alert sent id=1
```

In Telegram you will receive a message like:

```
📊 New Opportunity #1
Ticker: NVDA
Action: BUY
Confidence: 72%
...
Reply: YES 1 / NO 1 / INFO 1
```

Because `DRY_RUN=true`, replying `YES 1` will simulate the trade without
actually submitting an order to Alpaca.

---

## Part 8 — Enable paper trading (real Alpaca paper orders)

When you're satisfied that signals look sensible:

1. Open `.env` on the Mac Mini
   (edit in-place or re-upload via FileZilla with the change)

2. Change:
   ```
   DRY_RUN=false
   PAPER_TRADING=true
   ```

3. Restart the workers:
   ```bash
   # Stop: Ctrl+C in Terminal 1 and 2, then restart:
   python scripts/run_workers.py
   python scripts/run_telegram_bot.py
   ```

4. Send `STATUS` to your Telegram bot — it should show your paper account
   balance from Alpaca.

5. When the next opportunity arrives and you reply `YES <id>`, a real paper
   order will be placed on Alpaca and you will see it in the Alpaca dashboard
   under Paper Trading → Positions.

---

## Part 9 — Daemonise (run automatically, survive reboots)

### Workers service

```bash
# Copy the plist template
cp ~/PAE/deploy/com.pae.workers.plist ~/Library/LaunchAgents/

# Fill in your actual paths
sed -i '' "s|/path/to/PAE|$HOME/PAE|g" ~/Library/LaunchAgents/com.pae.workers.plist

# Load and start
launchctl load ~/Library/LaunchAgents/com.pae.workers.plist
launchctl list | grep pae   # should show the service
```

### Telegram bot service

```bash
# Duplicate the plist for the bot process
cp ~/Library/LaunchAgents/com.pae.workers.plist \
   ~/Library/LaunchAgents/com.pae.telegram.plist

# Edit the new plist — change 3 things:
#   com.pae.workers  →  com.pae.telegram
#   run_workers.py   →  run_telegram_bot.py
#   launchd-workers  →  launchd-telegram  (log file names)
nano ~/Library/LaunchAgents/com.pae.telegram.plist

launchctl load ~/Library/LaunchAgents/com.pae.telegram.plist
```

### Verify both are running

```bash
launchctl list | grep pae
# Should show two entries: com.pae.workers and com.pae.telegram

tail -f ~/PAE/logs/workers.log       # live worker log
tail -f ~/PAE/logs/launchd-workers.log  # launchd stdout
```

---

## Part 10 — Going live with real money (when you're ready)

**Do not do this until you have seen paper trades working correctly.**

1. Switch to a live Alpaca account:
   - Create a live account at alpaca.markets (requires identity verification)
   - Generate a new API key from the live dashboard
   - Upload an updated `.env` via FileZilla with the live keys

2. Change in `.env`:
   ```
   DRY_RUN=false
   PAPER_TRADING=false
   ```

3. Restart services via launchctl:
   ```bash
   launchctl stop  com.pae.workers  && launchctl start  com.pae.workers
   launchctl stop  com.pae.telegram && launchctl start  com.pae.telegram
   ```

> **Real money is at risk once both flags are false.**
> The Telegram approval gate is your only manual checkpoint — reply `YES`
> only when you have reviewed `INFO <id>` and are comfortable with the thesis.

---

## Summary: what goes where

| File | How it gets to the Mac Mini | Contains secrets? |
|------|-----------------------------|-------------------|
| All Python code | `git clone` / `git pull` from GitHub | No |
| `.env.development` | GitHub (safe — fake values) | No |
| `.env` | **FileZilla only** | **Yes** |
| `.env.production` | **FileZilla only** (rename to `.env`) | **Yes** |

---

## Quick reference: Telegram commands

Once the bot is running, you control everything from Telegram:

```
YES  <id>    Approve opportunity and place buy order
NO   <id>    Reject opportunity
INFO <id>    Show full thesis and coverage analysis
SELL NVDA    Close NVDA position
HOLD NVDA    Acknowledge alert, keep monitoring
STATUS       Portfolio snapshot with P/L
HELP         Full command reference
```
