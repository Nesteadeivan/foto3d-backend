@echo off
title Trabajador Foto3D - tu GPU
cd /d "%~dp0"
echo.
echo Antes de esto tiene que estar arrancado ComfyUI:
echo   D:\IA FOTO\comfyuirrancar.bat
echo.
".venv\Scripts\python.exe" worker.py
echo.
pause
