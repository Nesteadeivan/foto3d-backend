@echo off
title Foto3D - servidor
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Creando el entorno virtual, solo la primera vez...
    python -m venv .venv
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)

echo.
echo Arrancando Foto3D. Para pararlo, cierra esta ventana o pulsa Ctrl+C.
echo.
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000

echo.
echo El servidor se ha parado.
pause
