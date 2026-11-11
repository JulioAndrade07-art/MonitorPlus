@echo off
chcp 65001 >nul
echo ============================================================================
echo   DESINSTALADOR / LIMPEZA DE INICIALIZACAO - MONITORAMENTO DE PASTA
echo ============================================================================
echo.
echo Removendo entrada de inicializacao automatica do Registro do Usuario (HKCU)...
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "MonitoramentoDePasta" /f 2>nul
echo Encerrando processos em execucao...
taskkill /F /IM "MonitoramentoDePasta.exe" 2>nul
echo.
echo Inicializacao automatica removida com sucesso.
echo Nota: O banco de dados historico foi preservado em:
echo %LOCALAPPDATA%\MonitoramentoDePasta\database_monitor.db
pause
