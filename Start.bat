@echo off
title QUANT FLEET LAUNCHER
echo Rozpoczynam sekwencje startowa systemow V4.0...
timeout /t 2 /nobreak > NUL

:: 1. Uruchomienie Głównego Dashboardu (Katalog główny V4)
start "FLEET COMMANDER - DASHBOARD" cmd /k "cd /d "%~dp0" && python dashboard.py"

:: Krótki bufor czasowy na odciążenie procesora serwera
timeout /t 2 /nobreak > NUL

:: 2. Uruchomienie floty botów w izolowanych środowiskach
start "BOT: EURUSD" cmd /k "cd /d "%~dp0EURUSD" && python v4_mt5_eurusd_test.py"
start "BOT: GBPJPY" cmd /k "cd /d "%~dp0GBPJPY" && python v4_mt5_GBPJPY_test.py"
start "BOT: GER40" cmd /k "cd /d "%~dp0GER40" && python v4_mt5_GER40_test.py"
start "BOT: NZDUSD" cmd /k "cd /d "%~dp0NZDUSD" && python v4_mt5_NZDUSD_test.py"
start "BOT: US500" cmd /k "cd /d "%~dp0US500" && python v4_mt5_US500_test.py"

echo.
echo === FLOTA AKTYWNA I ZABEZPIECZONA ===
echo Mozesz zminimalizowac to okno.
pause