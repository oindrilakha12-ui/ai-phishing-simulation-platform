<#
  Run the evaluation suite; results are written to eval\results\*.json (labelled DEMO or LIVE).
      powershell -ExecutionPolicy Bypass -File scripts\eval.ps1
#>
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$py = "$root\backend\.venv\Scripts\python.exe"
& $py "$root\eval\dataset.py"
& $py "$root\eval\run_analyst_eval.py"
& $py "$root\eval\run_rag_eval.py"
& $py "$root\eval\run_guardrail_eval.py"
Write-Host "Results in $root\eval\results" -ForegroundColor Green
