@echo off
rem Builds dist\PokerCoach.exe: the coach as one program that needs no Python to run.
rem Double-clicked, that program starts the table app and opens its page in the browser.
setlocal
cd /d "%~dp0"
if not exist "tools\build_exe.py" goto nofiles
set "PY=python"
where py >nul 2>nul
if not errorlevel 1 set "PY=py -3"
%PY% --version >nul 2>nul
if errorlevel 1 goto nopython
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if errorlevel 1 goto oldpython
echo Installing the build tool. This happens once and needs the internet.
%PY% -m pip install "pyinstaller>=6"
if errorlevel 1 goto failed
%PY% -m pip install -r requirements-live.txt
if errorlevel 1 echo The old screen reader's libraries could not be installed: the program is built without it.
%PY% tools\build_exe.py --check
if errorlevel 1 goto failed
echo.
echo Done. The program is dist\PokerCoach.exe in this folder: double-click it to start the table app.
echo It saves your tables in PokerCoach\app in your user folder, not in this folder.
goto failed
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
endlocal
