$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

function Test-Python {
    param([string]$Command)
    try {
        $output = Invoke-Expression "$Command --version" 2>&1 | Out-String
        if ($LASTEXITCODE -eq 0 -and $output -match "Python 3\.(1[0-9]|[2-9][0-9])") {
            return $true
        }
    } catch {
        return $false
    }
    return $false
}

$launcher = $null
foreach ($candidate in @("py -3.12", "py -3.11", "py -3.10", "python")) {
    if (Test-Python $candidate) {
        $launcher = $candidate
        break
    }
}
if (-not $launcher) {
    Write-Error "Se necesita Python 3.10 o superior (python.org o el launcher 'py')."
}

Write-Host "Usando: $launcher"
Invoke-Expression "$launcher -m venv .venv"
if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    Write-Error "No se pudo crear .venv"
}

& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
& .\.venv\Scripts\python.exe -m pip install -e .

Write-Host @"
Entorno listo (Windows nativo).
1) Copy-Item config\config.example.toml config\config.toml
2) .\scripts\diagnostic_windows.ps1
3) .\scripts\run.ps1
4) .\scripts\run.ps1 -Simulate
5) .\scripts\run.ps1 -RealPrinter
"@
