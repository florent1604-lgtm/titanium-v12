@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "C:\Users\flore\Desktop\v12"
title TITANIUM - EXECUTION DEMO ARMEE
color 0E
echo ============================================================
echo   TITANIUM v12 - EXECUTION DEMO ARMEE
echo   Compte : Axi-US50-Demo (login 50061786) - DEMO uniquement
echo   Risque : 7%% / signal - limite par la marge (stop < 20%%)
echo   Le compte REEL (60261188) est protege : ordre refuse si
echo   le terminal n'est PAS sur le compte demo attendu.
echo ============================================================
echo.
echo Lancement... (fermer cette fenetre = arret du bot)
echo.
".\venv\Scripts\python.exe" main.py
echo.
echo [Bot arrete] Appuyez sur une touche pour fermer.
pause >nul
