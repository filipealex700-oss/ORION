@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === A criar o executavel do ORION (demora alguns minutos) ===
call venv\Scripts\activate || (echo Corre primeiro o instalar.bat & pause & exit /b 1)
pip install pyinstaller || (pause & exit /b 1)
pyinstaller --noconfirm --clean --onedir --windowed --name ORION ^
  --collect-all faster_whisper --collect-all ctranslate2 --collect-all onnxruntime ^
  --collect-all sounddevice --collect-all _sounddevice_data ^
  --hidden-import win32com.client --hidden-import pythoncom --hidden-import pywintypes ^
  main.py || (echo Falhou a criacao do exe. & pause & exit /b 1)
copy /Y config.json dist\ORION\ >nul
copy /Y README.md dist\ORION\ >nul
if exist orion_memoria.db copy /Y orion_memoria.db dist\ORION\ >nul
echo.
echo Pronto! O programa esta em  dist\ORION\ORION.exe
echo (Mantem a pasta ORION inteira junta. Podes criar um atalho para o ORION.exe no ambiente de trabalho.)
pause
