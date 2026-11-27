@echo off
REM Starts the REST API (docs at http://localhost:8000/docs).
cd /d "%~dp0"
echo Starting LabAssist API... documentation at http://localhost:8000/docs
".venv\Scripts\python.exe" -m uvicorn api:app --port 8000
pause
