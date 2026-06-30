#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if command -v pwsh >/dev/null 2>&1; then
  pwsh -NoProfile -ExecutionPolicy Bypass -File ./install-or-update.ps1
elif command -v powershell.exe >/dev/null 2>&1; then
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\\install-or-update.ps1
else
  echo "PowerShell was not found. On Windows, double-click install-or-update.cmd instead." >&2
  exit 1
fi
