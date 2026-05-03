$ErrorActionPreference = "Stop"

Set-Location (Resolve-Path "$PSScriptRoot\..")

Write-Host ""
Write-Host "DANGER: This will DELETE the NEYRA dev Postgres volume (all profiles/data)." -ForegroundColor Yellow
Write-Host "To confirm, type exactly: RESET NEYRA DB" -ForegroundColor Yellow
Write-Host ""

$confirmation = Read-Host "Type confirmation"
if ($confirmation -cne "RESET NEYRA DB") {
  Write-Host "Cancelled. Database was NOT reset." -ForegroundColor Green
  exit 1
}

docker compose down -v
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

docker compose up --build
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

