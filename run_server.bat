@echo off
cd /d "C:\Users\moosa\Documents\FYDP\Backend"
call venv\Scripts\activate.bat
set PYTHONIOENCODING=utf-8
set DEBUG=true
python main.py 2>&1
echo EXIT CODE: %errorlevel%
pause
