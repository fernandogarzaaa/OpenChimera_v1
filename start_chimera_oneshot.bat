@echo off
setlocal EnableDelayedExpansion

title CHIMERA QUANTUM ONE-SHOT LAUNCHER
color 0B

echo.
echo ========================================================
echo   CHIMERA QUANTUM LLM: One-Shot Launcher
echo ========================================================
echo.
echo [1/4] Cleaning up old processes...
taskkill /F /IM python.exe /T >nul 2>&1
taskkill /F /IM llama-server.exe /T >nul 2>&1
taskkill /F /IM uvicorn.exe /T >nul 2>&1
timeout /t 2 /nobreak >nul

echo [2/4] Starting Local LLM Backend (Qwen2.5-7B)...
echo        Flags: --n-gpu-layers 28 --flash-attn --cont-batching
cd /d D:\appforge-main\infrastructure\clawd-hybrid-rtx

REM Correct Model Path
set MODEL_PATH=src\models\Qwen2.5-7B-Instruct-Q4_K_M.gguf

if not exist "%MODEL_PATH%" (
    echo [ERROR] Model file not found at: %MODEL_PATH%
    echo         Run download_models.py first.
    pause
    exit /b 1
)

start "CHIMERA-Local-Backend" /min cmd /k "llama.cpp\server.exe -m %MODEL_PATH% -c 4096 -ngl 28 --cache-type-k f16 --cache-type-v f16 --flash-attn --cont-batching --parallel 2 --port 8080 --host 0.0.0.0 -t 8"

echo        Waiting for Local Backend (Port 8080)...
:WAIT_LOCAL
timeout /t 2 /nobreak >nul
curl -s http://localhost:8080/health >nul
if %errorlevel% neq 0 (
    echo        ...still waiting for Qwen to load...
    goto WAIT_LOCAL
)
echo [OK] Local Backend Ready!

echo [3/4] Starting CHIMERA Orchestrator (Port 7860)...
start "CHIMERA-Orchestrator" /min cmd /k "python -m uvicorn src.chimera_server:app --host 0.0.0.0 --port 7860 --log-level info"

echo        Waiting for Orchestrator (Port 7860)...
:WAIT_ORCH
timeout /t 2 /nobreak >nul
curl -s http://localhost:7860/health >nul
if %errorlevel% neq 0 (
    echo        ...still waiting for Chimera...
    goto WAIT_ORCH
)
echo [OK] CHIMERA Orchestrator Ready!

echo.
echo ========================================================
echo [4/4] SYSTEM ONLINE
echo ========================================================
echo  - Main API:   http://localhost:7860/v1
echo  - Local LLM:  http://localhost:8080
echo.
echo  Keep this window open. Closing it stops the system.
echo ========================================================
echo.

pause
