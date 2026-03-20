@echo off
REM CHIMERA ULTIMATE Launcher
REM Single command to start everything - won't disrupt OpenClaw
cd /d "%~dp0"

echo.
echo ========================================
echo   CHIMERA ULTIMATE - All-in-One Server
echo ========================================
echo.

REM Start CHIMERA ULTIMATE on port 7870 (won't conflict with OpenClaw)
set "PYTHON_EXE=C:\Program Files\Python314\python.exe"
set "LAUNCH_PYTHON="
if exist "%PYTHON_EXE%" (
	set "LAUNCH_PYTHON=%PYTHON_EXE%"
) else (
	echo Warning: Pinned Python not found at "%PYTHON_EXE%". Falling back to PATH python.
	set "LAUNCH_PYTHON=python"
)

echo Running CHIMERA preflight import checks...
"%LAUNCH_PYTHON%" -c "import importlib.util,sys;mods=['swarm_v2','token_fracture','smart_router','quantum_consensus_v2','simple_rag'];missing=[m for m in mods if importlib.util.find_spec(m) is None];print('Preflight OK' if not missing else 'Preflight missing modules: '+', '.join(missing));sys.exit(0 if not missing else 1)"
if errorlevel 1 (
	echo.
	echo CHIMERA preflight failed. Fix missing modules and retry.
	exit /b 1
)

start /B "CHIMERA ULTIMATE" cmd /c "cd /d D:\openclaw && "%LAUNCH_PYTHON%" chimera_ultimate.py"

echo.
echo Starting CHIMERA ULTIMATE on port 7870...
echo.
echo Features:
echo   - Local LLM (Ollama)
echo   - Swarm Orchestration
echo   - Token Fracture
echo   - Smart Router
echo   - Quantum Consensus
echo   - RAG Knowledge Base
echo   - Qwen-Agent Integration
echo.
echo API: http://localhost:7870
echo.

