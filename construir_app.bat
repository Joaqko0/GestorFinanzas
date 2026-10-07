@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Gestor de Finanzas - armando el programa
echo.
echo   Armando "Gestor de Finanzas.exe"
echo   La primera vez tarda unos minutos. No cierres esta ventana.
echo.

rem ---- 1) Buscar Python (solo hace falta para armar el .exe; despues ya no) ----
set "PY="
where py >nul 2>nul && py -3 -c "import sys" >nul 2>nul && set "PY=py -3"
if not defined PY (
    where python >nul 2>nul && python -c "import sys" >nul 2>nul && set "PY=python"
)
if not defined PY goto :sin_python
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" || goto :python_viejo
%PY% -c "import tkinter" >nul 2>nul || goto :sin_tk

rem ---- 2) Entorno aparte, para no tocar tu Python ----
echo [1/4] Preparando un entorno aparte (no toca tu Python)...
if not exist ".venv\Scripts\python.exe" (
    %PY% -m venv .venv || goto :error
)
set "VPY=.venv\Scripts\python.exe"

rem ---- 3) Librerias ----
echo [2/4] Instalando lo necesario (cryptography, openpyxl, pdfplumber, pyinstaller)...
"%VPY%" -m pip install --disable-pip-version-check -q --upgrade pip
"%VPY%" -m pip install --disable-pip-version-check -q -r requirements.txt pyinstaller || goto :error

rem ---- 4) Armar el .exe (un solo archivo, sin consola, con icono) ----
echo [3/4] Armando el .exe...
if exist "dist\Gestor de Finanzas.exe" del /q "dist\Gestor de Finanzas.exe" >nul 2>nul
"%VPY%" -m PyInstaller --noconfirm --clean --log-level WARN ^
    --onefile --windowed ^
    --name "Gestor de Finanzas" ^
    --icon icono.ico ^
    --add-data "icono.ico;." ^
    --collect-data pdfminer ^
    --collect-all pypdfium2 ^
    --collect-all pypdfium2_raw ^
    main.py || goto :error
if not exist "dist\Gestor de Finanzas.exe" goto :error

rem ---- 5) Dejarlo en el Escritorio ----
echo [4/4] Copiando el programa al Escritorio...
set "ESCRITORIO="
for /f "usebackq delims=" %%D in (`powershell -NoProfile -Command "[Environment]::GetFolderPath('Desktop')"`) do set "ESCRITORIO=%%D"
if not defined ESCRITORIO set "ESCRITORIO=%USERPROFILE%\Desktop"
copy /y "dist\Gestor de Finanzas.exe" "%ESCRITORIO%\" >nul && (
    echo.
    echo   Listo! "Gestor de Finanzas.exe" esta en tu Escritorio.
    echo   Abrilo con doble clic: ya no necesitas Python ni Visual Studio Code.
    echo   Tus datos siguen siendo los mismos ^(%APPDATA%\GestorFinanzas^).
) || (
    echo.
    echo   Listo! El programa quedo en la carpeta "dist" de esta carpeta.
)
echo.
explorer /select,"%ESCRITORIO%\Gestor de Finanzas.exe" >nul 2>nul
pause
exit /b 0

:sin_python
echo.
echo   No encontre Python. Hace falta solo para armar el .exe (despues ya no).
echo   1. Instalalo desde https://www.python.org/downloads/
echo   2. En el instalador marca "Add python.exe to PATH".
echo   3. Volve a hacer doble clic en este archivo.
start "" "https://www.python.org/downloads/"
pause
exit /b 1

:python_viejo
echo.
echo   Tu Python es muy viejo. Instala Python 3.9 o mas nuevo desde https://www.python.org/downloads/
pause
exit /b 1

:sin_tk
echo.
echo   Tu Python no tiene tkinter (la parte de las ventanas).
echo   Reinstala Python desde python.org y deja marcada la opcion "tcl/tk and IDLE".
pause
exit /b 1

:error
echo.
echo   Algo fallo armando el programa. Mira los mensajes de arriba.
echo   Si dice algo de "pip" o de internet, revisa la conexion y volve a intentar.
echo   Si el antivirus borro el .exe, agrega una excepcion para la carpeta "dist".
pause
exit /b 1
