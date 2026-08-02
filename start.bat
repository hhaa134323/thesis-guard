@echo off
chcp 65001 >nul
cd /d %~dp0
set PYTHONPATH=src
python -m thesis_watch.serve
pause
