<#
  Run all checks: backend lint/type/tests, frontend lint/type/unit tests.
  Add -E2E to also run Playwright (needs backend :8001 and frontend :3000 running, e.g. via dev.ps1).
      powershell -ExecutionPolicy Bypass -File scripts\test.ps1 [-E2E]
#>
param([switch]$E2E)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$failed = @()

function Step($name, [scriptblock]$block) {
  Write-Host "==> $name" -ForegroundColor Cyan
  & $block
  if ($LASTEXITCODE -ne 0) { $script:failed += $name; Write-Host "FAILED: $name" -ForegroundColor Red }
}

Push-Location "$root\backend"
Step "backend ruff"   { .\.venv\Scripts\ruff.exe check app tests }
Step "backend mypy"   { .\.venv\Scripts\mypy.exe app }
Step "backend pytest" { .\.venv\Scripts\python.exe -m pytest -o addopts="" --cov=app --cov-report=term -q }
Pop-Location

Push-Location "$root\frontend"
Step "frontend eslint" { npx eslint . }
Step "frontend tsc"    { npx tsc --noEmit }
Step "frontend vitest" { npx vitest run }
if ($E2E) { Step "frontend playwright" { npx playwright test } }
Pop-Location

if ($failed.Count) { Write-Host "Failed steps: $($failed -join ', ')" -ForegroundColor Red; exit 1 }
Write-Host "All checks passed." -ForegroundColor Green
