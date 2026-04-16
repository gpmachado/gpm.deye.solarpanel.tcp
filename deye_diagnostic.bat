@echo off
setlocal enabledelayedexpansion
title Deye Inverter Diagnostic
color 0A

echo.
echo  ============================================
echo   Deye Inverter Diagnostic Tool
echo  ============================================
echo.

:: ── Check Python ─────────────────────────────────────────────────────────────
python --version >nul 2>&1
if %errorlevel% neq 0 (
    py --version >nul 2>&1
    if !errorlevel! neq 0 (
        echo  [!] Python not found. Installing via winget...
        echo      This may take a few minutes.
        echo.
        winget install --id Python.Python.3.11 --source winget --accept-package-agreements --accept-source-agreements
        if !errorlevel! neq 0 (
            echo.
            echo  [ERROR] Could not install Python automatically.
            echo  Please install it manually from: https://www.python.org/downloads/
            echo  Then run this script again.
            pause
            exit /b 1
        )
        echo.
        echo  [OK] Python installed. Please close this window and run the script again.
        pause
        exit /b 0
    ) else (
        set PYTHON=py
    )
) else (
    set PYTHON=python
)

for /f "tokens=*" %%i in ('!PYTHON! --version 2^>^&1') do echo  [OK] %%i found
echo.

:: ── Install pysolarmanv5 ─────────────────────────────────────────────────────
echo  [..] Checking pysolarmanv5...
!PYTHON! -c "import pysolarmanv5" >nul 2>&1
if %errorlevel% neq 0 (
    echo  [..] Installing pysolarmanv5...
    !PYTHON! -m pip install pysolarmanv5 --quiet
    if !errorlevel! neq 0 (
        echo  [ERROR] Failed to install pysolarmanv5. Check internet connection.
        pause
        exit /b 1
    )
)
echo  [OK] pysolarmanv5 ready
echo.

:: ── Ask for connection details ───────────────────────────────────────────────
echo  Enter the details from Homey ^> Deye Inverter ^> Settings:
echo.
set /p HOST=  Logger IP Address  :
set /p SERIAL=  Logger Serial Number:
echo.

if "%HOST%"=="" (
    echo  [ERROR] IP address cannot be empty.
    pause
    exit /b 1
)
if "%SERIAL%"=="" (
    echo  [ERROR] Serial number cannot be empty.
    pause
    exit /b 1
)

:: ── Write the embedded Python diagnostic script ──────────────────────────────
set TMPSCRIPT=%TEMP%\deye_diag_run.py
(
echo import asyncio, sys
echo from pysolarmanv5 import PySolarmanV5Async
echo.
echo HOST   = "%HOST%"
echo SERIAL = %SERIAL%
echo MODEL  = "deye_hybrid"
echo.
echo DEFINITION = {
echo   "requests": [
echo     {"start":   3, "end": 116, "fc": 3},
echo     {"start": 150, "end": 249, "fc": 3},
echo     {"start": 250, "end": 279, "fc": 3},
echo   ],
echo   "sensors": [
echo     {"name":"PV1 Power",              "reg":[  11], "rule":1, "scale":1,   "off":0},
echo     {"name":"PV1 Voltage",            "reg":[  13], "rule":1, "scale":0.1, "off":0},
echo     {"name":"PV1 Current",            "reg":[  14], "rule":1, "scale":0.1, "off":0},
echo     {"name":"PV2 Power",              "reg":[  16], "rule":1, "scale":1,   "off":0},
echo     {"name":"PV2 Voltage",            "reg":[  17], "rule":1, "scale":0.1, "off":0},
echo     {"name":"PV2 Current",            "reg":[  18], "rule":1, "scale":0.1, "off":0},
echo     {"name":"Battery Power",          "reg":[ 190], "rule":2, "scale":1,   "off":0},
echo     {"name":"Battery Voltage",        "reg":[ 183], "rule":1, "scale":0.01,"off":0},
echo     {"name":"Battery Current",        "reg":[ 191], "rule":2, "scale":0.01,"off":0},
echo     {"name":"Battery SOC",            "reg":[ 184], "rule":1, "scale":1,   "off":0},
echo     {"name":"Battery Temperature",    "reg":[ 182], "rule":2, "scale":0.1, "off":1000},
echo     {"name":"Grid L1 Voltage",        "reg":[  76], "rule":1, "scale":0.1, "off":0},
echo     {"name":"Grid L1 Current",        "reg":[  78], "rule":2, "scale":0.01,"off":0},
echo     {"name":"Grid Frequency",         "reg":[  79], "rule":1, "scale":0.01,"off":0},
echo     {"name":"Grid Power",             "reg":[ 169], "rule":2, "scale":1,   "off":0},
echo     {"name":"Load Power",             "reg":[ 178], "rule":1, "scale":1,   "off":0},
echo     {"name":"AC Output Power",        "reg":[ 175], "rule":1, "scale":1,   "off":0},
echo     {"name":"DC Temperature",         "reg":[  90], "rule":2, "scale":0.1, "off":1000},
echo     {"name":"Radiator Temperature",   "reg":[  91], "rule":2, "scale":0.1, "off":1000},
echo     {"name":"Today Production",       "reg":[  60], "rule":1, "scale":0.1, "off":0},
echo     {"name":"Total Production",       "reg":[ 63,64],"rule":3,"scale":0.1, "off":0},
echo     {"name":"Today Battery Charge",   "reg":[ 166], "rule":1, "scale":0.1, "off":0},
echo     {"name":"Today Battery Discharge","reg":[ 167], "rule":1, "scale":0.1, "off":0},
echo     {"name":"Today Energy Import",    "reg":[ 250], "rule":1, "scale":0.1, "off":0},
echo     {"name":"Today Energy Export",    "reg":[ 251], "rule":1, "scale":0.1, "off":0},
echo     {"name":"Total Energy Import",    "reg":[252,253],"rule":3,"scale":0.1,"off":0},
echo     {"name":"Total Energy Export",    "reg":[254,255],"rule":3,"scale":0.1,"off":0},
echo   ]
echo }
echo.
echo async def main^(^):
echo     print^(f"\n  Connecting to {HOST}:8899  serial={SERIAL}..."^)
echo     m = PySolarmanV5Async^(HOST, SERIAL, port=8899, mb_slave_id=1, auto_reconnect=False, socket_timeout=15^)
echo     await m.connect^(^)
echo     print^("  Connected OK\n"^)
echo     raw = {}
echo     for req in DEFINITION["requests"]:
echo         s, e, fc = req["start"], req["end"], req["fc"]
echo         n = e - s + 1
echo         print^(f"  Reading [0x{s:X}..0x{e:X}] fc={fc}..."^)
echo         try:
echo             data = await m.read_holding_registers^(register_addr=s, quantity=n^) if fc==3 else await m.read_input_registers^(register_addr=s, quantity=n^)
echo             for i,v in enumerate^(data^): raw[s+i] = v
echo         except Exception as ex:
echo             print^(f"    ERROR: {ex}"^)
echo     await m.disconnect^(^)
echo     print^("\n  Raw registers ^(non-zero^):"^)
echo     for reg in sorted^(raw^):
echo         v = raw[reg]
echo         if v: print^(f"    reg {reg:4d} ^(0x{reg:04X}^) = {v:6d}  ^(0x{v:04X}^)"^)
echo     print^("\n  Parsed values:"^)
echo     for s in DEFINITION["sensors"]:
echo         regs = s["reg"]
echo         if not all^(r in raw for r in regs^): print^(f"  {s['name']:<36s} -- not read"^); continue
echo         if s["rule"]==3 and len^(regs^)>=2: rv = raw[regs[0]] + raw.get^(regs[1],0^)*65536
echo         else: rv = raw[regs[0]]
echo         val = ^(rv - s["off"]^) * s["scale"]
echo         print^(f"  {s['name']:<36s} {val:.2f}"^)
echo.
echo asyncio.run^(main^(^)^)
) > "%TMPSCRIPT%"

:: ── Run diagnostic and save output ──────────────────────────────────────────
set OUTFILE=%USERPROFILE%\Desktop\deye_diagnostic_%HOST%.txt
echo  Running diagnostic for %HOST% (serial: %SERIAL%)...
echo  Output will be saved to Desktop\deye_diagnostic_%HOST%.txt
echo.

(
    echo Deye Diagnostic — %DATE% %TIME%
    echo Host: %HOST%   Serial: %SERIAL%   Model: deye_hybrid
    echo ================================================================
    !PYTHON! "%TMPSCRIPT%"
) > "%OUTFILE%" 2>&1

type "%OUTFILE%"

echo.
echo  ============================================
echo   Done! File saved to Desktop:
echo   deye_diagnostic_%HOST%.txt
echo   Please send this file.
echo  ============================================
echo.
del "%TMPSCRIPT%" >nul 2>&1
pause
