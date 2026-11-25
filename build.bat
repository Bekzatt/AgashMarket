@echo off
REM Build dist\AgashMarket.exe. Requires Python 3.10+ and packages from requirements.txt.
cd /d "%~dp0"
python -m pip install -r requirements.txt "pyinstaller>=6.10,<7" || goto error
python -m PyInstaller --noconfirm --clean AgashMarket.spec || goto error
echo.
echo Done: dist\AgashMarket.exe
echo Put the .env file (database and bot settings) next to the exe.
pause
exit /b 0

:error
echo.
echo Build failed, see the messages above.
pause
exit /b 1