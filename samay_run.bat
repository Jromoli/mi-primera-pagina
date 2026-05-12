@echo off
cd /d "%~dp0"
python samay_monitor.py >> samay.log 2>&1
