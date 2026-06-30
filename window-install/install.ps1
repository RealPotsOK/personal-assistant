param(
    [string]$Source = "$PSScriptRoot\publish\win-x64",
    [switch]$NoAutoStart,
    [switch]$NoLaunch
)

$ErrorActionPreference = "Stop"
$InstallDir = Join-Path $env:LOCALAPPDATA "Programs\PersonalAssistant"
$Exe = Join-Path $InstallDir "PersonalAssistant.Windows.exe"
$StartMenuDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Personal Assistant"
$ShortcutPath = Join-Path $StartMenuDir "Personal Assistant.lnk"
if (-not (Test-Path $Source)) {
    throw "Published client folder was not found at '$Source'. Run .\scripts\publish-win-x64.ps1 first and make sure it succeeds."
}
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
Copy-Item -Path (Join-Path $Source "*") -Destination $InstallDir -Recurse -Force

New-Item -ItemType Directory -Force -Path $StartMenuDir | Out-Null
$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $Exe
$Shortcut.WorkingDirectory = $InstallDir
$Shortcut.Description = "Personal Assistant"
$Shortcut.IconLocation = "$Exe,0"
$Shortcut.Save()

if (-not $NoAutoStart) {
    New-ItemProperty `
        -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" `
        -Name "PersonalAssistant" `
        -Value "`"$Exe`"" `
        -PropertyType String `
        -Force | Out-Null
}

if (-not $NoLaunch) {
    Start-Process -FilePath $Exe -WorkingDirectory $InstallDir
}

Write-Host "Installed Personal Assistant to $InstallDir"
Write-Host "Start Menu shortcut created at $ShortcutPath"
