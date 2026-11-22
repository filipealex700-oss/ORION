@echo off
chcp 65001 >nul
echo === Instalacao do ORION ===
py -3 -m venv venv || (echo Instala o Python 3.10+ em python.org e marca "Add to PATH". & pause & exit /b 1)
call venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
echo.
echo A descarregar os modelos para o teu PC (preset gtx1660s, ~10 GB)...
python main.py --preset gtx1660s --descarregar
echo.
echo Pronto! Usa iniciar.bat para arrancar o ORION.
pause
