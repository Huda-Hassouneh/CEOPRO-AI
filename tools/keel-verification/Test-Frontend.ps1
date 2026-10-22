$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
Push-Location (Join-Path $repo 'frontend')
try {
  npm test
  if ($LASTEXITCODE -ne 0) { throw 'Frontend tests failed.' }
  npm run lint
  if ($LASTEXITCODE -ne 0) { throw 'Frontend lint failed.' }
  npm run build
  if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
} finally { Pop-Location }
