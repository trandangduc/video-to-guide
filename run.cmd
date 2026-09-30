@echo off
cd /d "%~dp0"
python -X utf8 app.py
if errorlevel 1 pause
