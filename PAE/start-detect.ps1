# Start the PAE detection worker on the Windows GPU host.
# Run from PowerShell:  .\start-detect.ps1
# Optional arg:         .\start-detect.ps1 propaganda-arbitrage
#
# Requires: SSH key at C:\Users\alexr\.ssh\id_rsa with access to chi206.greengeeks.net
# The script opens an SSH tunnel (local 3307 -> server MySQL 3306) so no IP
# whitelist is needed. Set DATABASE_URL in .env to use 127.0.0.1:3307.

param(
    [string]$Strategy = "propaganda-arbitrage"
)

$PAE_DIR    = Split-Path -Parent $MyInvocation.MyCommand.Path
$VENV_PYTHON = "$PAE_DIR\venv\Scripts\python.exe"
$SSH_KEY    = "$env:USERPROFILE\.ssh\id_rsa"
$SSH_HOST   = "alexmane@chi206.greengeeks.net"
$LOCAL_PORT = 3307

if (-not (Test-Path $VENV_PYTHON)) {
    Write-Error "venv not found at $PAE_DIR\venv"
    Write-Host "Run: cd $PAE_DIR; python -m venv venv; pip install -r requirements.txt"
    exit 1
}

# ── Open SSH tunnel ────────────────────────────────────────────────────────────
Write-Host "==> Opening SSH tunnel (127.0.0.1:$LOCAL_PORT -> MySQL on server)..."
$tunnel = Start-Process -FilePath "ssh" `
    -ArgumentList "-N", "-L", "${LOCAL_PORT}:localhost:3306",
                  "-i", $SSH_KEY,
                  "-o", "IdentitiesOnly=yes",
                  "-o", "ServerAliveInterval=60",
                  "-o", "ExitOnForwardFailure=yes",
                  $SSH_HOST `
    -PassThru -WindowStyle Hidden

# Give SSH a moment to establish the tunnel
Start-Sleep -Seconds 3

if ($tunnel.HasExited) {
    Write-Error "SSH tunnel failed to start (exit code $($tunnel.ExitCode)). Check key/host."
    exit 1
}

Write-Host "==> Tunnel open (PID $($tunnel.Id))"

# ── Start detection worker ─────────────────────────────────────────────────────
Write-Host "==> Starting PAE detection worker (strategy=$Strategy)"
Set-Location $PAE_DIR
try {
    & $VENV_PYTHON -m app.workers.tasks $Strategy --mode detect
} finally {
    # Clean up tunnel when worker exits (Ctrl-C or crash)
    Write-Host "==> Stopping SSH tunnel (PID $($tunnel.Id))..."
    Stop-Process -Id $tunnel.Id -Force -ErrorAction SilentlyContinue
}
