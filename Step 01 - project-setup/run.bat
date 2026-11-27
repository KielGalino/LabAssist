@echo off
REM Starts LabAssist with the venv's Python (no Activate.ps1 needed).
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo The .venv folder is missing. Create it first:
    echo    python -m venv .venv
    echo    .venv\Scripts\python.exe -m pip install -r requirements.txt
    pause
    exit /b 1
)
echo Starting LabAssist... open http://localhost:8501 in your browser.
".venv\Scripts\python.exe" -m streamlit run app.py
pause
