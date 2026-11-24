@echo off
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Creando entorno virtual .venv...
    python -m venv .venv
)

echo Instalando dependencias y PyInstaller...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt pyinstaller

echo Empaquetando POS para Windows 11...
".venv\Scripts\pyinstaller.exe" --clean --noconfirm pos.spec

if errorlevel 1 (
    echo Ocurrio un error al empaquetar.
    pause
    exit /b 1
)

echo.
echo Listo! El ejecutable quedo en: dist\POS\POS.exe
pause
