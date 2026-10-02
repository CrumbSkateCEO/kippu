#!/usr/bin/env pwsh
param(
    [switch]$RealPrinter,
    [switch]$Simulate,
    [switch]$Headless,
    [switch]$Diagnostic
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    Write-Error "No existe .venv. Ejecute primero scripts/bootstrap_windows.ps1"
}

$arguments = @("-m", "kippu", "--config", "config/config.toml")
if ($RealPrinter) { $arguments += "--real-printer" }
if ($Simulate) { $arguments += "--simulate" }
if ($Headless) { $arguments += "--headless" }
if ($Diagnostic) { $arguments += "--diagnostic" }

& .\.venv\Scripts\python.exe @arguments
exit $LASTEXITCODE
