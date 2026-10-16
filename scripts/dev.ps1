<#
  Start backend (FastAPI on :8001) and frontend (Next.js dev on :3000) in two new windows.
      powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
  Port 8001 is used because 8000 was occupied on the development machine; override with -BackendPort.
#>
param([int]$BackendPort = 8001, [int]$FrontendPort = 3000)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

if (-not (Test-Path "$root\backend\.venv\Scripts\python.exe")) {
  throw "Backend virtualenv missing. Run scripts\setup.ps1 first."
}

$backendCmd = "Set-Location '$root\backend'; .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port $BackendPort"
$frontendCmd = "Set-Location '$root\frontend'; `$env:BACKEND_URL='http://127.0.0.1:$BackendPort'; npm run dev -- -p $FrontendPort"

$b = Start-Process powershell -ArgumentList "-NoExit", "-Command", $backendCmd -PassThru
$f = Start-Process powershell -ArgumentList "-NoExit", "-Command", $frontendCmd -PassThru

Write-Host "Backend  -> http://127.0.0.1:$BackendPort/docs   (pid $($b.Id))" -ForegroundColor Green
Write-Host "Frontend -> http://localhost:$FrontendPort        (pid $($f.Id))" -ForegroundColor Green
Write-Host "Demo login: admin@globex.example.com / PhishGuard!2026 (synthetic demo data only)"

# Wait until the backend answers so the user knows it's up.
for ($i = 0; $i -lt 40; $i++) {
  try {
    $r = Invoke-RestMethod "http://127.0.0.1:$BackendPort/health/ready" -TimeoutSec 2
    Write-Host "Backend ready: database=$($r.database) demo_mode=$($r.demo_mode)" -ForegroundColor Green
    break
  } catch { Start-Sleep -Milliseconds 750 }
}
