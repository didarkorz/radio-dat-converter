@echo off
cd /d "%~dp0"
python radio_gui.py
if errorlevel 1 pause
