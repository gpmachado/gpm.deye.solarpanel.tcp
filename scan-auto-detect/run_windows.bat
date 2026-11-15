@echo off
setlocal

set "SCRIPT_DIR=%~dp0"

echo.
echo  ============================================
echo   Deye Auto Detect (Windows)
echo  ============================================
echo.

rem "where python" also finds the Microsoft Store stub, which opens the Store
rem and exits without running anything - so check that Python really starts.
py -3 --version >nul 2>nul
if %errorlevel%==0 (
  py -3 "%SCRIPT_DIR%deye_auto_detect.py" %*
  goto :done
)

python --version >nul 2>nul
if %errorlevel%==0 (
  python "%SCRIPT_DIR%deye_auto_detect.py" %*
  goto :done
)

echo  [ERROR] Python 3 is not installed (or not in PATH).
echo  Install it from https://www.python.org/downloads/ and tick
echo  "Add python.exe to PATH" during setup, then run this again.
echo.
pause
exit /b 1

:done
set "RC=%errorlevel%"
echo.
if not "%RC%"=="0" echo  The scan stopped with an error - see the messages above.
rem Keep the window open so the result or error can be read.
pause
exit /b %RC%
