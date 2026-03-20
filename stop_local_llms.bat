@echo off
REM CHIMERA Local LLM Stop Script
REM Stops all llama.cpp servers

echo.
echo ╔══════════════════════════════════════════════════════╗
echo ║     CHIMERA LOCAL LLM - Stopping Servers            ║
echo ╚══════════════════════════════════════════════════════╝
echo.

echo Stopping llama.cpp servers...
echo.

taskkill /FI "WINDOWTITLE eq CHIMERA-Qwen2.5-7B*" /T /F 2>nul
taskkill /FI "WINDOWTITLE eq CHIMERA-Gemma-2-9B*" /T /F 2>nul
taskkill /FI "WINDOWTITLE eq CHIMERA-Llama-3.2-3B*" /T /F 2>nul
taskkill /FI "WINDOWTITLE eq CHIMERA-Phi-3.5-Mini*" /T /F 2>nul

echo.
echo ✅ All local LLM servers stopped.
echo.
pause
