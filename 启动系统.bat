@echo off
title 对公信贷智能化辅助系统

echo.
echo   ==========================================
echo       对公信贷智能化辅助系统
echo   ==========================================
echo.

cd /d "%~dp0bank_credit_assist"

echo   [1/3] Checking Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo   ERROR: Python not found
    pause
    exit /b 1
)
echo         Python OK

echo   [2/3] Checking dependencies...
python -c "import fastapi" >nul 2>&1
if errorlevel 1 (
    echo         Installing...
    pip install -r requirements.txt -q
)
echo         Dependencies OK

echo   [3/3] Starting server on port 8001...
echo.
echo   ==========================================
echo   Open http://localhost:8001 in browser
echo   Press Ctrl+C to stop
echo   ==========================================
echo.

start http://localhost:8001
python -m uvicorn server:app --host 0.0.0.0 --port 8001

pause
