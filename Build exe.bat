@echo off
rem Builds dist\PokerCoach.exe: the coach as one program that needs no Python to run.
setlocal
cd /d "%~dp0"
set "PY=python"
where py >nul 2>nul
if not errorlevel 1 set "PY=py -3"
%PY% --version >nul 2>nul
if errorlevel 1 goto nopython
echo Installing the build tools. This happens once and needs the internet.
%PY% -m pip install -r requirements-live.txt pyinstaller
if errorlevel 1 goto failed
%PY% tools\build_exe.py
if errorlevel 1 goto failed
echo.
echo Done. The program is dist\PokerCoach.exe in this folder.
echo It keeps its own files in the PokerCoach folder of your user folder.
goto failed
:nopython
echo Python is not installed on this computer.
echo Get it from https://www.python.org/downloads/ and tick "Add python.exe to PATH" in the installer.
echo Then double-click this file again.
:failed
echo.
pause
endlocal
