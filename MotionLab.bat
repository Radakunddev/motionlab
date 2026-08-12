@echo off
setlocal
set "ROOT=%~dp0"

rem --- apply a staged self-update (downloaded by the app while it was running)
if exist "%ROOT%update_staging\READY" (
  echo Applying MotionLab update...
  robocopy "%ROOT%update_staging\payload" "%ROOT%" /E /NFL /NDL /NJH /NJS >nul
  if errorlevel 8 (
    echo Update copy failed, starting the current version instead.
  ) else (
    del "%ROOT%update_staging\READY" >nul 2>&1
    rd /s /q "%ROOT%update_staging\payload" >nul 2>&1
    del "%ROOT%update_staging\update.zip" >nul 2>&1
  )
)

rem --- first run on a fresh machine: fetch engine, python env and models
if not exist "%ROOT%engine\venv\Scripts\pythonw.exe" (
  echo First start: MotionLab needs to download its engine and models.
  powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%installer\bootstrap.ps1"
  if errorlevel 1 (
    echo.
    echo Setup did not finish. Run MotionLab again to retry.
    pause
    exit /b 1
  )
)

start "MotionLab" "%ROOT%engine\venv\Scripts\pythonw.exe" "%ROOT%app\main.py"
endlocal
