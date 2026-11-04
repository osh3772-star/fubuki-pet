@echo off
setlocal
cd /d "%~dp0"
if not exist "dist\latest-build.txt" (echo Build with build_windows.cmd first. & exit /b 1)
set /p BUNDLE=<"dist\latest-build.txt"
".venv\Scripts\python.exe" tools\build_program.py --pack-only "%BUNDLE%"
exit /b %errorlevel%
