@echo off
setlocal
cd /d "%~dp0"
set "AQA4_PY=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if not exist "%AQA4_PY%" set "AQA4_PY=python"
set "PYTHONPATH=%CD%\.deps;%USERPROFILE%\.codex\visualizations\2026\11\03\01a1a25e-4988-7163-973a-37953f97705e\aqa4_dashboard_deps;%PYTHONPATH%"
"%AQA4_PY%" -c "import streamlit, pandas, pyarrow" 2>nul
if errorlevel 1 (
  "%AQA4_PY%" -m pip install -r requirements.txt --target .deps --upgrade --disable-pip-version-check
  if errorlevel 1 (
    pause
    exit /b 1
  )
)
"%AQA4_PY%" -m streamlit run app.py --server.address 127.0.0.1
if errorlevel 1 pause
