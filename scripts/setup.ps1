<#
  One-time setup on Windows (PowerShell). Run from the repo root:
      powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
  Creates the Python venv, installs backend + frontend dependencies, copies .env.example,
  migrates the SQLite database and seeds synthetic demo data.
#>
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "==> Backend: virtualenv + dependencies" -ForegroundColor Cyan
if (-not (Test-Path "backend\.venv")) { python -m venv backend\.venv }
& backend\.venv\Scripts\python.exe -m pip install --upgrade pip -q
& backend\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt -q
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

if (-not (Test-Path "backend\.env")) {
  Copy-Item .env.example backend\.env
  # Generate a real random JWT secret for this machine.
  $secret = & backend\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
  (Get-Content backend\.env) -replace '^JWT_SECRET=.*', "JWT_SECRET=$secret" | Set-Content backend\.env -Encoding utf8
  Write-Host "    created backend\.env with a random JWT_SECRET"
}

Write-Host "==> Database: migrate + seed (SQLite by default)" -ForegroundColor Cyan
Push-Location backend
& .venv\Scripts\alembic.exe upgrade head
if ($LASTEXITCODE -ne 0) { Pop-Location; throw "alembic upgrade failed" }
& .venv\Scripts\python.exe -m app.seed
Pop-Location

Write-Host "==> Frontend: npm install" -ForegroundColor Cyan
Push-Location frontend
npm install --no-fund --no-audit
if ($LASTEXITCODE -ne 0) { Pop-Location; throw "npm install failed" }
Pop-Location

Write-Host "Setup complete. Start everything with: powershell -ExecutionPolicy Bypass -File scripts\dev.ps1" -ForegroundColor Green
