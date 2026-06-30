param(
    [string]$Source = "$PSScriptRoot\publish\win-x64",
    [switch]$NoAutoStart
)

$ErrorActionPreference = "Stop"
$InstallDir = Join-Path $env:LOCALAPPDATA "Programs\PersonalAssistant"
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
