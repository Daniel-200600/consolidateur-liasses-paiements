@echo off
setlocal EnableExtensions
chcp 65001 >nul
title Construction de Analyse.exe

cd /d "%~dp0"

echo ============================================
echo   CONSTRUCTION DE ANALYSE.EXE - PYTHON 3.11
echo ============================================
echo.

echo [1/5] Verification de Python 3.11...
py -3.11 --version >nul 2>nul
if errorlevel 1 (
    echo [ERREUR] Python 3.11 n'est pas accessible avec le lanceur Python.
    echo.
    echo Executez dans CMD : py -0p
    echo et verifiez que Python 3.11 apparait.
    pause
    exit /b 1
)
py -3.11 --version

echo.
echo [2/5] Creation de l'environnement de build Python 3.11...
if exist ".build_venv" (
    echo Suppression de l'ancien environnement de build...
    rmdir /s /q ".build_venv"
)
py -3.11 -m venv .build_venv
if errorlevel 1 goto :error

.build_venv\Scripts\python.exe --version
if errorlevel 1 goto :error

echo.
echo [3/5] Installation des dependances du projet...
.build_venv\Scripts\python.exe -m pip install --upgrade pip
if errorlevel 1 goto :error

.build_venv\Scripts\python.exe -m pip install -r consolidateur\requirements.txt
if errorlevel 1 goto :error

.build_venv\Scripts\python.exe -m pip install pyinstaller
if errorlevel 1 goto :error

echo.
echo [4/5] Nettoyage des anciens builds...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo [5/5] Generation de Analyse.exe...
.build_venv\Scripts\pyinstaller.exe --clean --noconfirm Analyse.spec
if errorlevel 1 goto :error

if not exist "dist\Analyse.exe" goto :error

echo.
echo ============================================
echo   BUILD TERMINE AVEC SUCCES
echo ============================================
echo.
echo Executable :
echo   %~dp0dist\Analyse.exe
echo.
echo Double-cliquez sur Analyse.exe pour lancer l'application.
echo.
pause
exit /b 0

:error
echo.
echo ============================================
echo   [ERREUR] LA CONSTRUCTION A ECHOUE
echo ============================================
echo Consultez le message affiche ci-dessus.
pause
exit /b 1
