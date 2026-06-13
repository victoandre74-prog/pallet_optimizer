@echo off
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERREUR] Environnement virtuel introuvable.
    echo Lancez d'abord install.bat
    pause
    exit /b 1
)

echo ============================================
echo   Optimiseur Pallet - port 8050
echo ============================================
echo Fermer cette fenetre pour arreter l'application.
echo.

.venv\Scripts\python app_optimizer.py

echo.
echo [Application arretee]
pause
