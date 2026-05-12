@echo off
setlocal

set "ROOT=%~dp0"
py -3 -m codex_memory export --project-root "%ROOT%"
if errorlevel 1 exit /b %errorlevel%

codex %*
