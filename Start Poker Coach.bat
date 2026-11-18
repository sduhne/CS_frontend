@echo off
rem Starts the poker coach from this folder. Everything it needs and everything it saves stays here.
setlocal
cd /d "%~dp0"
set "PY=python"
where py >nul 2>nul
if not errorlevel 1 set "PY=py -3"
%PY% --version >nul 2>nul
if errorlevel 1 goto nopython
%PY% -c "import PIL, mss, pydantic, tkinter" >nul 2>nul
if not errorlevel 1 goto run
echo Installing what the coach needs. This happens once and needs the internet.
%PY% -m pip install -r requirements-live.txt
if errorlevel 1 goto failed
:run
%PY% -m poker_coach live-app
if errorlevel 1 goto failed
goto end
:nopython
echo Python is not installed on this computer.
echo Get it from https://www.python.org/downloads/ and tick "Add python.exe to PATH" in the installer.
echo Then double-click this file again.
:failed
echo.
pause
:end
endlocal
