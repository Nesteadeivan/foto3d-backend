# Arranca el servidor Foto3D. Doble clic no funciona: abre PowerShell aqui y ejecuta  .\run.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $py)) {
    Write-Host "Creando el entorno virtual (solo la primera vez)..." -ForegroundColor Cyan
    python -m venv (Join-Path $root ".venv")
    & $py -m pip install --upgrade pip
    & $py -m pip install -r (Join-Path $root "requirements.txt")
}

$port = if ($env:FOTO3D_PORT) { $env:FOTO3D_PORT } else { "8000" }
# 0.0.0.0 para que el movil pueda entrar desde la red local.
& $py -m uvicorn app.main:app --host 0.0.0.0 --port $port
