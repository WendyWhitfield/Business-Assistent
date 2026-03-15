@echo off
title Gwen — Business-Assistentin
echo.
echo  Gwen wird gestartet...
echo.
cd /d "%~dp0"
start "" "http://localhost:5000"
python app.py
pause
