@echo off
setlocal
cd /d "%~dp0"

echo ============================================
echo   Installation Pallet Optimizer
echo ============================================
echo.

REM -- Verifier Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] Python introuvable.
    echo Installez Python 3.11+ depuis https://python.org et relancez.
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo Python detecte : %%v

REM -- Creer le venv si absent
if exist ".venv\Scripts\python.exe" (
    echo Environnement virtuel existant detecte, mise a jour...
) else (
    echo Creation de l'environnement virtuel...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERREUR] Impossible de creer l'environnement virtuel.
        pause
        exit /b 1
    )
)

REM -- Mettre a jour pip
echo Mise a jour de pip...
.venv\Scripts\python -m pip install --upgrade pip --quiet

REM -- Installer les dependances
echo Installation des dependances ^(requirements.txt^)...
.venv\Scripts\pip install -r requirements.txt
if errorlevel 1 (
    echo [ERREUR] Installation des dependances echouee.
    pause
    exit /b 1
)

REM -- Installer le package
echo Installation du package pallet_optimizer...
.venv\Scripts\pip install .
if errorlevel 1 (
    echo [ERREUR] Installation du package echouee.
    pause
    exit /b 1
)

echo.
echo ============================================
echo   Installation terminee avec succes !
echo ============================================
echo.
echo Utilisez start_optimizer.bat  pour lancer l'optimiseur  ^(port 8050^)
echo Utilisez start_visualizer.bat pour lancer le visualiseur ^(port 8053^)
echo.
pause
