@echo off
cd /d "C:\Users\Abdul Wasay\Documents\office work elivenAi\EduMaster\backend"
call venv\Scripts\activate.bat
python main.py 2>&1
echo EXIT CODE: %errorlevel%
pause
