$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

Write-Host ""
Write-Host "=== Personal Assistant Windows install/update ==="
Write-Host ""

if (-not (Get-Command dotnet -ErrorAction SilentlyContinue)) {
    throw ".NET 8 SDK was not found. Install it from https://dotnet.microsoft.com/download/dotnet/8.0"
}

dotnet test .\PersonalAssistant.Windows.sln
if ($LASTEXITCODE -ne 0) {
    throw "dotnet test failed with exit code $LASTEXITCODE"
}

.\scripts\publish-win-x64.ps1
.\install.ps1

Write-Host ""
Write-Host "Done. Personal Assistant is installed."
