param(
    [string]$Configuration = "Release"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
dotnet publish "$Root\src\PersonalAssistant.Windows\PersonalAssistant.Windows.csproj" `
    -c $Configuration `
    -r win-x64 `
    --self-contained true `
    -p:PublishSingleFile=true `
    -p:IncludeNativeLibrariesForSelfExtract=true `
    -o "$Root\publish\win-x64"
Write-Host "Published to $Root\publish\win-x64"
