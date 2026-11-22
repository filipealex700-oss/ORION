@echo off
REM Compila o módulo Rust do ORION para integração com Python
echo A compilar módulo Rust do ORION...
cd rust_modules

REM Verificar se Rust está instalado
rustc --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERRO: Rust não está instalado!
    echo Instale em: https://rustup.rs/
    pause
    exit /b 1
)

REM Instalar maturin se não estiver instalado
pip show maturin >nul 2>&1
if %errorlevel% neq 0 (
    echo A instalar maturin...
    pip install maturin
)

REM Compilar com maturin
echo A compilar com maturin (pode demorar alguns minutos)...
maturin develop --release

if %errorlevel% neq 0 (
    echo ERRO na compilação do módulo Rust
    pause
    exit /b 1
)

echo.
echo ============================================
echo SUCESSO! Módulo Rust compilado e instalado
echo ============================================
echo.
echo Para testar, execute:
echo   python testar_latencia.py
echo.
pause
