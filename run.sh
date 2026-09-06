#!/usr/bin/env bash
# Arranca el servidor Foto3D (Linux / macOS / Git Bash)
set -e
cd "$(dirname "$0")"
PY=.venv/Scripts/python.exe
[ -f "$PY" ] || PY=.venv/bin/python
if [ ! -f "$PY" ]; then
  echo "Creando el entorno virtual (solo la primera vez)..."
  python -m venv .venv
  [ -f .venv/Scripts/python.exe ] && PY=.venv/Scripts/python.exe || PY=.venv/bin/python
  "$PY" -m pip install -r requirements.txt
fi
exec "$PY" -m uvicorn app.main:app --host 0.0.0.0 --port "${FOTO3D_PORT:-8000}"
