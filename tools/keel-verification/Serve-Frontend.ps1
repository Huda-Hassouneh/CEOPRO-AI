$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
Push-Location (Join-Path $repo 'frontend')
try { npm run dev -- --host 127.0.0.1 --port 5178 --strictPort } finally { Pop-Location }
