#!/usr/bin/env pwsh
param(
    [switch]$Once,
    [switch]$RealPrinter,
    [switch]$Simulate,
    [switch]$Headless,
    [switch]$Diagnostic
)

$ErrorActionPreference = "Continue"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    Write-Error "No existe .venv. Ejecute primero scripts/bootstrap_windows.ps1"
    exit 1
}

if (-not (Test-Path ".\config\config.toml")) {
    Write-Error "Falta config/config.toml. Copie config/config.example.toml."
    exit 1
}

$env:PYTHONPATH = if ($env:PYTHONPATH) { "$projectRoot\src;$env:PYTHONPATH" } else { "$projectRoot\src" }

function Invoke-Stage {
    param(
        [string]$Name,
        [string[]]$PythonArgs
    )
    Write-Host ""
    Write-Host "======== $Name ========"
    Write-Host "Cerre la ventana para pasar a la siguiente etapa."
    Write-Host ""
    & .\.venv\Scripts\python.exe @PythonArgs
    $code = $LASTEXITCODE
    Write-Host ""
    Write-Host "← $Name cerrado (codigo $code). Siguiente etapa en 1s..."
    Start-Sleep -Seconds 1
}

$kippuArgs = @("-m", "kippu", "--config", "config/config.toml")
if ($RealPrinter) { $kippuArgs += "--real-printer" }
if ($Simulate) { $kippuArgs += "--simulate" }
if ($Headless) { $kippuArgs += "--headless" }
if ($Diagnostic) { $kippuArgs += "--diagnostic" }

try {
    while ($true) {
        Invoke-Stage -Name "El Bienvenidor" -PythonArgs $kippuArgs
        Invoke-Stage -Name "Viernes" -PythonArgs @("-m", "viernes.core.main")
        if ($Once) {
            Write-Host "Pasada unica terminada."
            break
        }
        Write-Host "Reiniciando ciclo..."
    }
}
catch {
    Write-Host "Show detenido."
}
