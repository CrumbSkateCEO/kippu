$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    Write-Error "No existe .venv. Ejecute primero scripts/bootstrap_windows.ps1"
}

$arguments = @("-m", "kippu", "--config", "config/config.toml", "--diagnostic")
if ($args -contains "-RealPrinter" -or $args -contains "-real-printer") {
    $arguments += "--real-printer"
}

& .\.venv\Scripts\python.exe @arguments
exit $LASTEXITCODE
