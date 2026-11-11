@echo off
chcp 65001 >nul
if exist "%LOCALAPPDATA%\MonitoramentoDePasta\dist\MonitoramentoDePasta.exe" (
    start "" "%LOCALAPPDATA%\MonitoramentoDePasta\dist\MonitoramentoDePasta.exe"
) else (
    start "" pythonw "%~dp0monitoramento_de_pasta\main.py"
)
