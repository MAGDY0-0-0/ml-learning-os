@echo off
rem One-time setup: puts an "ML Journey" icon on the Desktop and in the Start
rem menu. After this you never need a terminal to open the app.
rem   install-shortcuts.bat            the icons
rem   install-shortcuts.bat autostart  ...and start the server when you sign in
cd /d "%~dp0"
if /i "%1"=="autostart" (
  .venv\Scripts\python.exe -m app.launcher --install --autostart
) else (
  .venv\Scripts\python.exe -m app.launcher --install
)
pause
