@echo off
rem Starts the older program, the one that reads the poker table from the screen (play-money tables only).
rem The table app, where you type the table yourself, is "Start Poker Coach.bat".
setlocal
title Menlo Coach screen reader
cd /d "%~dp0"
if not exist "poker_coach\live\wizard.py" goto nofiles
set "PY=python"
where py >nul 2>nul
if not errorlevel 1 set "PY=py -3"
%PY% --version >nul 2>nul
if errorlevel 1 goto nopython
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if errorlevel 1 goto oldpython
%PY% -c "import PIL, mss, pydantic, tkinter" >nul 2>nul
if not errorlevel 1 goto run
echo Installing what the screen reader needs. This happens once and needs the internet.
%PY% -m pip install -r requirements-live.txt
if errorlevel 1 goto failed
:run
%PY% -m poker_coach live-app
if errorlevel 1 goto failed
goto end
:nofiles
echo The coach's files are not next to this file.
echo Unpack the whole zip first (right-click it, Extract All), then start this file from the unpacked folder.
goto failed
:nopython
echo Python is not installed on this computer.
echo Get it from https://www.python.org/downloads/ and tick "Add python.exe to PATH" in the installer.
echo Then double-click this file again.
goto failed
:oldpython
echo The Python on this computer is too old: the coach needs Python 3.10 or newer.
echo Get it from https://www.python.org/downloads/ and tick "Add python.exe to PATH" in the installer.
echo Then double-click this file again.
:failed
echo.
pause
:end
endlocal
