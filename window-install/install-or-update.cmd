@echo off
setlocal
cd /d "%~dp0"

echo.
echo === Personal Assistant Windows install/update ===
echo.

where dotnet >nul 2>nul
if errorlevel 1 (
  echo ERROR: .NET 8 SDK was not found. Install it from:
  echo https://dotnet.microsoft.com/download/dotnet/8.0
  pause
  exit /b 1
)

echo Running tests...
dotnet test .\PersonalAssistant.Windows.sln
if errorlevel 1 (
  echo.
  echo Tests failed. The app will not be installed.
  pause
  exit /b 1
)

echo.
echo Publishing win-x64 build...
powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\publish-win-x64.ps1"
if errorlevel 1 (
  echo.
  echo Publish failed.
  pause
  exit /b 1
)

echo.
echo Installing...
powershell -NoProfile -ExecutionPolicy Bypass -File ".\install.ps1"
if errorlevel 1 (
  echo.
  echo Install failed.
  pause
  exit /b 1
)

echo.
echo Done. Personal Assistant is installed.
pause
