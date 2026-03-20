@echo off
REM CHIMERA Unified Launcher
REM Starts all CHIMERA services with one command

echo.
echo ========================================
echo   CHIMERA QUANTUM LLM - Launcher
echo ========================================
echo.

REM Check if Ollama is running
echo [1/5] Checking Ollama...
curl -s http://localhost:11434/ >nul 2>&1
if %errorlevel% neq 0 (
    echo     Ollama not running. Starting...
    start "" ollama serve
    timeout /t 3 /nobreak >nul
) else (
    echo     Ollama already running
)

REM Check if llama.cpp server is running
echo [2/5] Checking llama.cpp server...
curl -s http://localhost:8080/health >nul 2>&1
if %errorlevel% neq 0 (
    echo     Starting llama.cpp server...
    start "" cmd /c "cd /d D:\appforge-main\infrastructure\clawd-hybrid-rtx\llama.cpp\build\bin\Release && llama-server.exe -m D:\appforge-main\infrastructure\clawd-hybrid-rtx\src\models\Qwen2.5-7B-Instruct-Q4_K_M.gguf -c 4096 --port 8080 --host 0.0.0.0 -t 8"
    timeout /t 5 /nobreak >nul
) else (
    echo     llama.cpp already running
)

REM Start CHIMERA Simple (port 7861)
echo [3/5] Starting CHIMERA Simple (port 7861)...
start "" cmd /c "cd /d D:\openclaw && python chimera_simple.py"

REM Start CHIMERA Swarm (port 7862)  
echo [4/5] Starting CHIMERA Swarm (port 7862)...
start "" cmd /c "cd /d D:\openclaw && python chimera_swarm.py"

REM Start CHIMERA V2 (port 7863)
echo [5/5] Starting CHIMERA V2 (port 7863)...
start "" cmd /c "cd /d D:\openclaw && python chimera_v2.py"

echo.
echo ========================================
echo   All services started!
echo ========================================
echo.
echo Ports:
echo   7861 - CHIMERA Simple
echo   7862 - CHIMERA Swarm  
echo   7863 - CHIMERA V2
echo   8080 - llama.cpp (CPU)
echo   11434 - Ollama (GPU)
echo.
echo ========================================
echo.
echo Press any key to exit (services keep running)...
pause >nul
