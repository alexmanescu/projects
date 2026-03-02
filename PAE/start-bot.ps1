# Start the PAE Telegram bot listener on the Windows host.
# Run from PowerShell:  .\start-bot.ps1
#
# The bot listener writes pause/resume flags to the DB worker_controls table.
# Workers (scrape + detect) check those flags at the top of every cycle.
# Only needs to run on ONE machine — Windows is recommended (always-on).

$PAE_DIR    = Split-Path -Parent $MyInvocation.MyCommand.Path
$VENV_PYTHON = "$PAE_DIR\venv\Scripts\python.exe"

if (-not (Test-Path $VENV_PYTHON)) {
    Write-Error "venv not found at $PAE_DIR\venv"
    Write-Host "Run: cd $PAE_DIR; python -m venv venv; pip install -r requirements.txt"
    exit 1
}

Write-Host "==> Starting PAE Telegram bot listener..."
Set-Location $PAE_DIR
& $VENV_PYTHON -m app.workers.bot_listener
