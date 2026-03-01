# PAE Deployment Guide

## Topology

```
┌──────────────────────────────────┐      ┌──────────────────────────────────┐
│  Mac Mini (workers)              │      │  GreenGeeks (chi206.greengeeks.net)│
│                                  │      │                                  │
│  • scripts/run_workers.py        │─────▶│  alexmane_pae_core (MySQL 8.0)   │
│  • scripts/run_telegram_bot.py   │      │                                  │
│  • Ollama (qwen3-coder:30b)      │      │  web/  (PHP dashboard)           │
│  • Python 3.11 virtualenv        │      │                                  │
└──────────────────────────────────┘      └──────────────────────────────────┘
```

---

## Step 1 — MySQL on GreenGeeks

> **Already done?** If the database and user exist, skip to
> "Allow remote connections" and verify the connection string.

### Create database and user

GreenGeeks cPanel automatically prepends your account name (`alexmane_`) to
every database and username — you cannot avoid this prefix.

In cPanel → **MySQL Databases**:

1. **Create Database** → enter `pae_core` → cPanel saves it as `alexmane_pae_core`
2. **Create User** → enter `pae_user` + a strong password → saved as `alexmane_pae_user`
3. **Add User to Database** → select `alexmane_pae_user` + `alexmane_pae_core` → grant **ALL PRIVILEGES**

### Allow remote connections

In cPanel → **Remote MySQL**:

1. Add your Mac Mini's public IP address
   (check [whatismyip.com](https://whatismyip.com) from the Mac Mini's network)
2. Save

Test from the Mac Mini:

```bash
mysql -h chi206.greengeeks.net -u alexmane_pae_user -p alexmane_pae_core -e "SELECT 1;"
```

### Connection string

```
DATABASE_URL=mysql+pymysql://alexmane_pae_user:YOUR_PASSWORD@chi206.greengeeks.net:3306/alexmane_pae_core
```

---

## Step 2 — Mac Mini Setup

### System dependencies

```bash
# Install Homebrew if not present
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Python 3.11
brew install python@3.11

# Ollama
brew install ollama
ollama pull qwen3-coder:30b
```

### Clone and configure PAE

```bash
cd ~
git clone https://github.com/yourrepo/PAE.git
cd PAE

python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.development .env
# Fill in DATABASE_URL, ALPACA_API_KEY, ALPACA_SECRET_KEY,
# TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
nano .env
```

### Initialise the database

```bash
source venv/bin/activate
python -c "from app.core.database import init_db; init_db(); print('Tables created')"
```

### Register and activate the propaganda-arbitrage strategy

```python
# Run this once:
from app.core.database import db_session
from app.core.strategy_loader import StrategyLoader
from app.models import Strategy

with db_session() as db:
    StrategyLoader().register_strategy(db, "propaganda-arbitrage")
    s = db.query(Strategy).filter_by(name="propaganda-arbitrage").first()
    s.is_active = True
    db.commit()
```

---

## Step 3 — Run Services Manually (verify before daemonising)

```bash
# Terminal 1: workers
source venv/bin/activate
python scripts/run_workers.py

# Terminal 2: Telegram bot
source venv/bin/activate
python scripts/run_telegram_bot.py
```

Send `HELP` to your Telegram bot to confirm it responds.
Send `STATUS` to confirm it can reach the broker.

---

## Step 4 — Daemonise with launchd (macOS)

### Workers service

```bash
# 1. Copy the plist
cp deploy/com.pae.workers.plist ~/Library/LaunchAgents/

# 2. Replace placeholders
sed -i '' "s|/path/to/PAE|$HOME/PAE|g" ~/Library/LaunchAgents/com.pae.workers.plist
sed -i '' "s|YOUR_USERNAME|$USER|g"     ~/Library/LaunchAgents/com.pae.workers.plist

# 3. Load
launchctl load ~/Library/LaunchAgents/com.pae.workers.plist

# 4. Verify
launchctl list | grep pae
```

### Telegram bot service

Create `~/Library/LaunchAgents/com.pae.telegram.plist` by copying
`com.pae.workers.plist` and changing:

- `<string>com.pae.workers</string>` → `<string>com.pae.telegram</string>`
- `scripts/run_workers.py` → `scripts/run_telegram_bot.py`
- Log paths to `launchd-telegram.log`

Then:

```bash
launchctl load ~/Library/LaunchAgents/com.pae.telegram.plist
```

### Useful launchd commands

```bash
launchctl stop  com.pae.workers
launchctl start com.pae.workers
launchctl unload ~/Library/LaunchAgents/com.pae.workers.plist

tail -f ~/PAE/logs/workers.log
tail -f ~/PAE/logs/launchd-workers.log
```

---

## Step 4 (Linux alternative) — systemd

```bash
sudo cp deploy/pae-workers.service /etc/systemd/system/
sudo sed -i "s|YOUR_USERNAME|$USER|g"  /etc/systemd/system/pae-workers.service
sudo sed -i "s|/path/to/PAE|$HOME/PAE|g" /etc/systemd/system/pae-workers.service

sudo systemctl daemon-reload
sudo systemctl enable  pae-workers
sudo systemctl start   pae-workers
sudo systemctl status  pae-workers
```

Logs:

```bash
sudo journalctl -u pae-workers -f
tail -f ~/PAE/logs/workers.log
```

---

## Step 5 — Alpaca Account

1. Sign up at [alpaca.markets](https://alpaca.markets)
2. Go to **Paper Trading** dashboard → generate API key + secret
3. Add to `.env`:

```
ALPACA_API_KEY=PKXXXXXXXXXXXXXXXXXX
ALPACA_SECRET_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
PAPER_TRADING=true
DRY_RUN=false
```

> Keep `DRY_RUN=true` for initial testing — no trades will be executed.
> Set `DRY_RUN=false` only when you are ready to send paper orders.
> Set `PAPER_TRADING=false` only when you are ready for real money.

---

## Step 6 — Telegram Bot

1. Open Telegram, message [@BotFather](https://t.me/BotFather)
2. `/newbot` → choose a name and username
3. Copy the token to `TELEGRAM_BOT_TOKEN` in `.env`
4. Get your chat ID: message your bot anything, then visit
   `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy `chat.id`
5. Add to `.env`:

```
TELEGRAM_BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ
TELEGRAM_CHAT_ID=987654321
```

---

## Monitoring

### Log locations

| File | Contents |
|------|----------|
| `logs/workers.log` | Python app logs — scrapers, LLM, trades (rotating 10 MB × 3) |
| `logs/launchd-workers.log` | launchd stdout/stderr redirect |
| `logs/telegram.log` | Telegram bot process logs |

### Health check

```bash
source venv/bin/activate
python -c "
from app.workers.health import check_system_health
import json
print(json.dumps(check_system_health(), indent=2))
"
```

Expected output when all systems operational:

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

### Checking open positions

Send `STATUS` to your Telegram bot, or query the DB directly:

```sql
SELECT ticker, quantity, avg_entry_price, current_price,
       ROUND((current_price / avg_entry_price - 1) * 100, 2) AS pnl_pct
FROM positions
ORDER BY opened_at DESC;
```

---

## Backup

### Database backup

```bash
mysqldump -h chi206.greengeeks.net -u alexmane_pae_user -p alexmane_pae_core \
  --single-transaction --routines > pae_backup_$(date +%Y%m%d).sql
```

Set up a daily cron on the Mac Mini:

```cron
0 3 * * * ~/PAE/venv/bin/python -c "
import subprocess, datetime, pathlib
out = pathlib.Path.home() / 'pae-backups'
out.mkdir(exist_ok=True)
fname = out / f'pae_{datetime.date.today()}.sql'
subprocess.run(['mysqldump', '-h', 'chi206.greengeeks.net',
                '-u', 'alexmane_pae_user', '-pYOUR_PASSWORD',
                'alexmane_pae_core', '--single-transaction', '-r', str(fname)])
"
```

### `.env` backup

Keep `.env` in a password manager (1Password, Bitwarden) — **never commit it
to git**.  The `.gitignore` already excludes it.

---

## Updating PAE

```bash
cd ~/PAE
git pull origin main
source venv/bin/activate
pip install -r requirements.txt   # install any new deps

# Re-run migrations if schema changed:
python -c "from app.core.database import init_db; init_db()"

# Restart services:
launchctl stop  com.pae.workers  && launchctl start  com.pae.workers
launchctl stop  com.pae.telegram && launchctl start  com.pae.telegram
```
