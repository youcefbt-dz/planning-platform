@echo off
cd /d "%~dp0"
if exist .venv\Scripts\activate.bat call .venv\Scripts\activate.bat
start "" http://localhost:5000
flask run
pause
