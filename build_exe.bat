@echo off
chcp 65001 >nul
echo ============================================================================
echo   COMPILADOR DO EXECUTAVEL WINDOWS - MONITORAMENTO DE PASTA (MonitorPlus)
echo ============================================================================
echo.

set "OUT_DIR=%LOCALAPPDATA%\MonitoramentoDePasta"
if not exist "%OUT_DIR%" mkdir "%OUT_DIR%"

python -B "%~dp0monitoramento_de_pasta\assets\icon_generator.py"

python -B -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --onefile ^
    --windowed ^
    --name "MonitoramentoDePasta" ^
    --icon "%LOCALAPPDATA%\MonitoramentoDePasta\assets\icon.ico" ^
    --paths "%~dp0monitoramento_de_pasta" ^
    --distpath "%OUT_DIR%\dist" ^
    --workpath "%OUT_DIR%\build" ^
    --specpath "%OUT_DIR%" ^
    --exclude-module matplotlib ^
    --exclude-module numpy ^
    --exclude-module pandas ^
    --exclude-module reportlab ^
    --exclude-module openpyxl ^
    --exclude-module pypdf ^
    --exclude-module pytest ^
    --exclude-module PySide6.QtWebEngineCore ^
    --exclude-module PySide6.QtWebEngineWidgets ^
    --exclude-module PySide6.QtQuick ^
    --exclude-module PySide6.QtQml ^
    --exclude-module PySide6.QtPdf ^
    --exclude-module PySide6.Qt3DCore ^
    "%~dp0monitoramento_de_pasta\main.py"

echo.
echo Executavel compilado com sucesso em:
echo %OUT_DIR%\dist\MonitoramentoDePasta.exe
