$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
try {
    $running = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/health' -TimeoutSec 2
} catch { $running = $null }
if ($running -and $running.status -eq 'ok' -and $running.PSObject.Properties.Name -contains 'ai_mode') {
    Write-Host 'QQ assistant is already running at http://127.0.0.1:8000. No second instance started.'
    return
}
$envPython = Join-Path $PSScriptRoot '.venv-local/Scripts/python.exe'
$validEnvironment = $false
if (Test-Path -LiteralPath $envPython) {
    & $envPython -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>$null
    $validEnvironment = $LASTEXITCODE -eq 0
}
if (-not $validEnvironment) {
    $candidates = @('python', (Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'))
    $basePython = $null
    foreach ($candidate in $candidates) {
        if (-not (Get-Command $candidate -ErrorAction SilentlyContinue)) { continue }
        & $candidate -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>$null
        if ($LASTEXITCODE -eq 0) { $basePython = $candidate; break }
    }
    if (-not $basePython) { throw 'Python 3.10 or newer is required. Install Python 3.12, then reopen this terminal.' }
    Write-Host 'Creating a working Python environment...'
    & $basePython -m venv .venv-local
    if ($LASTEXITCODE -ne 0) { throw 'Failed to create the Python environment.' }
}
& $envPython -c 'import fastapi, uvicorn, httpx, cryptography, dotenv' 2>$null
if ($LASTEXITCODE -ne 0) {
    & $envPython -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Failed to install dependencies.' }
}
if (-not (Test-Path -LiteralPath '.env')) { Copy-Item -LiteralPath '.env.example' -Destination '.env' }
Write-Host 'Open http://127.0.0.1:8000 in your browser. Press Ctrl+C to stop.'
& $envPython -m uvicorn app.main:app --host 127.0.0.1 --port 8000
