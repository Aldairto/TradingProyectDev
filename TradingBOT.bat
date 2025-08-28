@echo off
cd /d "C:\Users\ARTO3\Documents\Trading\ProyectoBotTrading\executor_mt5"

echo [INFO] Iniciando Trading BOT Executor

:: Ejecutar mt5_executor.py en nueva ventana
start "MT5 Executor" py mt5_executor.py


echo [INFO] Ambos procesos se han lanzado. Monitoreando cada 5 segundos.
pause
