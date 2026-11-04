@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  call setup_windows.cmd
  if errorlevel 1 goto error
)
if not exist "logs" mkdir "logs"
".venv\Scripts\python.exe" -m pip install -r requirements-build.txt > "logs\build-dependencies.log" 2>&1
if errorlevel 1 goto error
".venv\Scripts\python.exe" tools\build_program.py > "logs\build.log" 2>&1
if errorlevel 1 goto error
type "logs\build.log"
echo Build complete. Keep the whole FubukiPet folder together.
exit /b 0
:error
echo Build failed. See logs\build.log and logs\build-dependencies.log.
exit /b 1
