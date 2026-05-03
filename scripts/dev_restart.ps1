$ErrorActionPreference = "Stop"

Set-Location (Resolve-Path "$PSScriptRoot\..")

docker compose down
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

docker compose up --build
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

