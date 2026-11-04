@echo off
setlocal
cd /d "%~dp0"
if not "%OS%"=="Windows_NT" exit /b 2
if not exist "logs" mkdir "logs"
if exist ".venv\Scripts\python.exe" goto install
py -3 -c "import sys; assert (3,11) <= sys.version_info[:2] <= (3,13)" >nul 2>&1
if not errorlevel 1 (
  py -3 -m venv .venv
  if errorlevel 1 goto error
  goto install
)
python -c "import sys; assert (3,11) <= sys.version_info[:2] <= (3,13)" >nul 2>&1
if not errorlevel 1 (
  python -m venv .venv
  if errorlevel 1 goto error
  goto install
)
for %%V in (313 312 311) do if not defined PYTHON_EXE if exist "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe" set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe"
if not defined PYTHON_EXE goto error
"%PYTHON_EXE%" -m venv .venv
if errorlevel 1 goto error
:install
".venv\Scripts\python.exe" -m pip install -r requirements.txt > "logs\setup.log" 2>&1
if errorlevel 1 goto error
".venv\Scripts\python.exe" -c "import PySide6; from windows_pet.core import Settings; print('Ready')" >> "logs\setup.log" 2>&1
if errorlevel 1 goto error
echo Ready. Double-click START_FUBUKI.cmd.
exit /b 0
:error
echo Setup failed. Python 3.11-3.13 x64 and Internet access are required.
echo If Python is not installed, install it from https://www.python.org/downloads/windows/
echo See logs\setup.log for details.
exit /b 1
