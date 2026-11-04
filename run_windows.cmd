@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  call setup_windows.cmd
  if errorlevel 1 (pause & exit /b 1)
)
".venv\Scripts\python.exe" launcher.py %*
set "code=%errorlevel%"
if not "%code%"=="0" (echo Fubuki failed. See %%LOCALAPPDATA%%\FubukiPet\logs. & pause)
exit /b %code%
