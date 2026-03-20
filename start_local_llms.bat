@echo off
REM CHIMERA Local LLM Startup Script
REM Starts multiple llama.cpp servers for RTX 2060 optimization

echo.
echo ╔══════════════════════════════════════════════════════╗
echo ║     CHIMERA LOCAL LLM - RTX 2060 Startup            ║
echo ╚══════════════════════════════════════════════════════╝
echo.

REM Configuration
set LLAMA_SERVER=D:\appforge-main\infrastructure\clawd-hybrid-rtx\llama.cpp\build-cuda\bin\llama-server.exe
set MODELS_DIR=D:\appforge-main\infrastructure\clawd-hybrid-rtx\src\models
set LOG_DIR=logs

REM Create directories if they don't exist
if not exist "%MODELS_DIR%" mkdir "%MODELS_DIR%"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

REM Check if llama.cpp server exists
if not exist "%LLAMA_SERVER%" (
    echo [ERROR] llama.cpp server not found: %LLAMA_SERVER%
    echo.
    echo Please install llama.cpp with CUDA support:
    echo   1. git clone https://github.com/ggerganov/llama.cpp
    echo   2. Build with: cmake -DGGML_CUDA=ON
    echo   3. Copy server.exe to llama.cpp\
    echo.
    pause
    exit /b 1
)

REM Check if models exist
set MODEL_COUNT=0
if exist "%MODELS_DIR%\qwen2.5-7b-instruct-q4_k_m.gguf" set /a MODEL_COUNT+=1
if exist "%MODELS_DIR%\gemma-2-9b-it-q4_k_m.gguf" set /a MODEL_COUNT+=1
if exist "%MODELS_DIR%\llama-3.2-3b-instruct-q8_0.gguf" set /a MODEL_COUNT+=1
if exist "%MODELS_DIR%\phi-3.5-mini-instruct-q8_0.gguf" set /a MODEL_COUNT+=1

if %MODEL_COUNT% EQU 0 (
    echo [WARNING] No models found in %MODELS_DIR%
    echo.
    echo Download models first:
    echo   python download_models.py --all
    echo.
    pause
    exit /b 1
)

echo Found %MODEL_COUNT% model(s)
echo.

REM Start Qwen2.5-7B (Primary - Port 8080)
if exist "%MODELS_DIR%\qwen2.5-7b-instruct-q4_k_m.gguf" (
    echo [STARTING] Qwen2.5-7B on port 8080...
    echo Optimization flags: --n-gpu-layers 28 --flash-attn --cont-batching --parallel 2
    start "CHIMERA-Qwen2.5-7B" cmd /k "%LLAMA_SERVER% -m %MODELS_DIR%\qwen2.5-7b-instruct-q4_k_m.gguf -c 4096 -ngl 28 --cache-type-k f16 --cache-type-v f16 --flash-attn --cont-batching --parallel 2 --port 8080 --host 0.0.0.0 -t 8"
    timeout /t 3 /nobreak >nul
)

REM Start Gemma-2-9B (Secondary - Port 8081)
if exist "%MODELS_DIR%\gemma-2-9b-it-q4_k_m.gguf" (
    echo [STARTING] Gemma-2-9B on port 8081...
    start "CHIMERA-Gemma-2-9B" cmd /k "%LLAMA_SERVER% -m %MODELS_DIR%\gemma-2-9b-it-q4_k_m.gguf -c 4096 -ngl 20 --cache-type-k f16 --cache-type-v f16 --flash-attn --port 8081 --host 0.0.0.0 -t 8"
    timeout /t 3 /nobreak >nul
)

REM Start Llama-3.2-3B (Fast - Port 8082)
if exist "%MODELS_DIR%\llama-3.2-3b-instruct-q8_0.gguf" (
    echo [STARTING] Llama-3.2-3B on port 8082...
    start "CHIMERA-Llama-3.2-3B" cmd /k "%LLAMA_SERVER% -m %MODELS_DIR%\llama-3.2-3b-instruct-q8_0.gguf -c 4096 -ngl 25 --flash-attn --port 8082 --host 0.0.0.0 -t 8"
    timeout /t 3 /nobreak >nul
)

REM Start Phi-3.5-Mini (Ultra-fast - Port 8083)
if exist "%MODELS_DIR%\phi-3.5-mini-instruct-q8_0.gguf" (
    echo [STARTING] Phi-3.5-Mini on port 8083...
    start "CHIMERA-Phi-3.5-Mini" cmd /k "%LLAMA_SERVER% -m %MODELS_DIR%\phi-3.5-mini-instruct-q8_0.gguf -c 4096 -ngl 25 --flash-attn --port 8083 --host 0.0.0.0 -t 8"
    timeout /t 3 /nobreak >nul
)

echo.
echo ╔══════════════════════════════════════════════════════╗
echo ║  Local LLM Servers Started!                          ║
echo ╚══════════════════════════════════════════════════════╝
echo.
echo Endpoints:
echo   - Qwen2.5-7B:    http://localhost:8080
echo   - Gemma-2-9B:    http://localhost:8081
echo   - Llama-3.2-3B:  http://localhost:8082
echo   - Phi-3.5-Mini:  http://localhost:8083
echo.
echo Health checks:
echo   - curl http://localhost:8080/health
echo.
echo To stop: Close the server windows or run stop_local_llms.bat
echo.
pause
