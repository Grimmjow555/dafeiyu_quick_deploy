@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 goto no_python

python -c "import PyQt5" >nul 2>nul
if errorlevel 1 goto no_pyqt

python -c "import dafeiyu_gui" >nul 2>nul
if errorlevel 1 goto no_package

for /f "delims=" %%I in ('python -c "import sys;print(sys.executable)"') do set "PYEXE=%%I"
if not defined PYEXE goto no_python

set "PYW=%PYEXE:python.exe=pythonw.exe%"
if not exist "%PYW%" set "PYW=%PYEXE%"

start "" "%PYW%" -m dafeiyu_gui
exit /b 0

:no_python
echo [ERROR] Python 3 was not found on PATH.
echo Install Python 3.10+ first, then run:
echo     python -m pip install -r requirements-gui.txt
pause
exit /b 1

:no_pyqt
echo [ERROR] PyQt5 is not installed for this Python.
echo Run:
echo     python -m pip install -r requirements-gui.txt
pause
exit /b 1

:no_package
echo [ERROR] The dafeiyu_gui package could not be imported.
echo Make sure run_gui.bat stays in the project root next to the dafeiyu_gui folder.
pause
exit /b 1
