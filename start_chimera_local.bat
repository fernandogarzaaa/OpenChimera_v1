@echo off
REM CHIMERA Local LLM Startup Script
REM Starts multiple llama.cpp servers for RTX 2060 optimization

echo.
echo ================================================
echo    CHIMERA LOCAL LLM - RTX 2060 Startup
echo ================================================
echo.

set LLAMA_SERVER=D:\appforge-main\infrastructure\clawd-hybrid-rtx\llama.cpp\build\bin\Release\llama-server.exe
set MODELS_DIR=D:\appforge-main\infrastructure\clawd-hybrid-rtx\src\models

REM Check if llama.cpp server exists
if not exist "%LLAMA_SERVER%" (
    echo [ERROR] llama.cpp server not found!
    echo Please build llama.cpp first.
    pause
    exit /b 1
)

echo Found llama-server.exe
echo Models directory: %MODELS_DIR%
echo.

REM Check available models
set MODEL_COUNT=0
if exist "%MODELS_DIR%\qwen2.5-7b-instruct-q4_k_m.gguf" (
    echo [FOUND] Qwen2.5-7B
call :start_server "qwen2.5-7b-instruct-q4_k_m.gguf" 8080 "CHIMERA-Qwen2.5-7B"
    set /a MODEL_COUNT+=1
)
if exist "%MODELS_DIR%\gemma-2-9b-it-q4_k_m.gguf" (
    echo [FOUND] Gemma-2-9B
    call :start_server "gemma-2-9b-it-q4_k_m.gguf" 8081 "CHIMERA-Gemma-2-9B"
    set /a MODEL_COUNT+=1
)
if exist "%MODELS_DIR%\Llama-3.2-3B-Instruct-Q8_0.gguf" (
    echo [FOUND] Llama-3.2-3B
    call :start_server "Llama-3.2-3B-Instruct-Q8_0.gguf" 8082 "CHIMERA-Llama-3.2-3B"
    set /a MODEL_COUNT+=1
)
if exist "%MODELS_DIR%\Phi-3.5-mini-instruct-Q8_0.gguf" (
    echo [FOUND] Phi-3.5-Mini
    call :start_server "Phi-3.5-mini-instruct-Q8_0.gguf" 8083 "CHIMERA-Phi-3.5-Mini"
    set /a MODEL_COUNT+=1
)

echo.
echo ================================================
echo Started %MODEL_COUNT% local LLM servers
echo ================================================
echo.
echo Endpoints:
echo   - Qwen2.5-7B:    http://localhost:8080
echo   - Gemma-2-9B:    http://localhost:8081
echo   - Llama-3.2-3B:  http://localhost:8082
echo   - Phi-3.5-Mini:  http://localhost:8083
echo.
echo Test: curl http://localhost:8080/health
echo.
pause
exit /b 0

:start_server
set MODEL_FILE=%~1
set PORT=%~2
set WINDOW_TITLE=%~3
echo [STARTING] %WINDOW_TITLE% on port %PORT%...
start "%WINDOW_TITLE%" cmd /k "\"%LLAMA_SERVER%\" -m \"%MODELS_DIR%\%MODEL_FILE%\" -c 4096 --port %PORT% --host 0.0.0.0 -t 8 2^>^&1"
timeout /t 2 /nobreak >nul
goto :eof
