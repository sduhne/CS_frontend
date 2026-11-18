@echo off
rem Starts the table app from this folder: a page in your browser where you type what happens at
rem your table and the coach answers. It needs Python 3.10 or newer and nothing else: nothing is
rem installed and the internet is not used. Your tables are saved in this folder, in tournament\app.
setlocal
title Poker Coach
cd /d "%~dp0"
if not exist "poker_coach\app\server.py" goto nofiles
set "PY=python"
where py >nul 2>nul
if not errorlevel 1 set "PY=py -3"
%PY% --version >nul 2>nul
if errorlevel 1 goto nopython
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if errorlevel 1 goto oldpython
echo Poker Coach: the page opens in your browser. Keep this window open while you use it.
echo To stop the coach, close this window.
echo.
%PY% -m poker_coach app
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
