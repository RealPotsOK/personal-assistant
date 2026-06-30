param(
    [string]$Source = "$PSScriptRoot\publish\win-x64",
    [switch]$NoAutoStart
)

$ErrorActionPreference = "Stop"
$InstallDir = Join-Path $env:LOCALAPPDATA "Programs\PersonalAssistant"
if (-not (Test-Path $Source)) {
    throw "Published client folder was not found at '$Source'. Run .\scripts\publish-win-x64.ps1 first and make sure it succeeds."
}
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
Copy-Item -Path (Join-Path $Source "*") -Destination $InstallDir -Recurse -Force

if (-not $NoAutoStart) {
    $Exe = Join-Path $InstallDir "PersonalAssistant.Windows.exe"
    New-ItemProperty `
        -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" `
        -Name "PersonalAssistant" `
        -Value "`"$Exe`"" `
        -PropertyType String `
        -Force | Out-Null
}

Write-Host "Installed Personal Assistant to $InstallDir"
