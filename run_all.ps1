<#
.SYNOPSIS
  Install, migrate, seed the offline demo, and start Boardom (backend + frontend).

.EXAMPLE
  .\run_all.ps1                     # dev servers on 8000 / 3000, demo data seeded
  .\run_all.ps1 -NoSeed             # skip the demo course
  .\run_all.ps1 -Prod               # production frontend build (next build + start)
  .\run_all.ps1 -BackendPort 8001 -FrontendPort 3001
  Press Ctrl+C to stop both servers.
#>
param(
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 3000,
    [switch]$NoSeed,
    [switch]$Prod
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

function Need($command, $hint) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        Write-Host "Missing '$command'. $hint" -ForegroundColor Red
        exit 1
    }
}
function Step($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }
function Check($what) { if ($LASTEXITCODE -ne 0) { Write-Host "$what failed." -ForegroundColor Red; exit 1 } }

Need "uv" "Install it: https://docs.astral.sh/uv/getting-started/installation/"
Need "node" "Install Node.js 22.13 or newer: https://nodejs.org/"
Need "npm" "npm comes with Node.js: https://nodejs.org/"

# The browser origin must match the frontend port (CSRF check); the proxy must find the API.
$env:BOARDOM_FRONTEND_ORIGIN = "http://localhost:$FrontendPort"
$env:BACKEND_URL = "http://127.0.0.1:$BackendPort"

Step "Backend: environment, dependencies, database"
Set-Location (Join-Path $root "backend")
if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env"; Write-Host "Created backend/.env from .env.example" }
uv sync; Check "uv sync"
uv run alembic upgrade head; Check "Database migration"
if (-not $NoSeed) {
    Step "Seeding the offline demo course"
    uv run python -m app.seed_demo; Check "Demo seed"
}

Step "Frontend: environment and dependencies"
Set-Location (Join-Path $root "frontend")
if (-not (Test-Path ".env.local")) { Copy-Item ".env.example" ".env.local"; Write-Host "Created frontend/.env.local" }
npm install --no-audit --no-fund; Check "npm install"
if ($Prod) { npm run build; Check "Frontend build" }

Step "Starting the servers"
$backend = Start-Process -PassThru -NoNewWindow -WorkingDirectory (Join-Path $root "backend") `
    -FilePath "uv" -ArgumentList @("run", "uvicorn", "app.main:app", "--port", "$BackendPort")
$script = if ($Prod) { "start" } else { "dev" }
$frontend = Start-Process -PassThru -NoNewWindow -WorkingDirectory (Join-Path $root "frontend") `
    -FilePath "npm.cmd" -ArgumentList @("run", $script, "--", "--port", "$FrontendPort")

try {
    $deadline = (Get-Date).AddSeconds(120)
    $ready = $false
    while ((Get-Date) -lt $deadline -and -not $ready) {
        Start-Sleep -Seconds 2
        try {
            $null = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$BackendPort/health" -TimeoutSec 3
            $null = Invoke-WebRequest -UseBasicParsing "http://localhost:$FrontendPort/login" -TimeoutSec 30
            $ready = $true
        } catch { }
    }
    if ($ready) {
        Write-Host "`nBoardom is running." -ForegroundColor Green
    } else {
        Write-Host "`nThe servers are still starting (or failed: see the output above)." -ForegroundColor Yellow
    }
    Write-Host "  App:      http://localhost:$FrontendPort   (use localhost, not 127.0.0.1)"
    Write-Host "  API docs: http://127.0.0.1:$BackendPort/docs"
    Write-Host "  Admin:    admin@example.com / BoardomAdmin#2026 (change it!)"
    if (-not $NoSeed) {
        Write-Host "  Teacher:  demo.teacher@example.com / DemoTeacher#2026"
        Write-Host "  Student:  asha@example.com / DemoStudent#2026"
    }
    Write-Host "Press Ctrl+C to stop."
    Wait-Process -Id $backend.Id, $frontend.Id
} finally {
    foreach ($p in @($backend, $frontend)) {
        if ($p -and -not $p.HasExited) { & taskkill /T /F /PID $p.Id *> $null }
    }
    Set-Location $root
}
