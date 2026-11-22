@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PATH=%PATH%;%CD%\venv\Lib\site-packages\nvidia\cublas\bin
set PATH=%PATH%;%CD%\venv\Lib\site-packages\nvidia\cuda_runtime\bin
set PATH=%PATH%;%CD%\venv\Lib\site-packages\nvidia\cudnn\bin
call venv\Scripts\activate.bat
python main.py --web %*
if errorlevel 1 pause
