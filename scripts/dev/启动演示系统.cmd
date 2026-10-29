@echo off
setlocal
powershell.exe -NoLogo -NoProfile -File "%~dp0Start-PrototypeStack.ps1" -PrepareDemo -InteractiveScenario -OpenBrowser
if errorlevel 1 pause
