@echo off
echo =======================================================
echo Starting AReaL RL Training Loop against CHIMERA Ultimate
echo =======================================================

set GATEWAY_URL=http://localhost:7870/v1
set ADMIN_KEY=sk-test123456

echo Running demo_lifecycle.py
python D:\appforge-main\AReaL\examples\openclaw\demo_lifecycle.py %GATEWAY_URL% --admin-key %ADMIN_KEY%

if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Training loop failed.
    exit /b %ERRORLEVEL%
)

echo.
echo [SUCCESS] Training loop completed.
