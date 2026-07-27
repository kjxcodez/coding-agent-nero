@echo off
echo ==========================================
echo   NERO CLI Local Installation Helper
echo ==========================================
echo.
echo Installing NERO in editable mode...
pip install -e .

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Installation failed.
    exit /b %errorlevel%
)

echo.
echo ==========================================
echo   [SUCCESS] NERO CLI Installed!
echo ==========================================
echo.
echo You can now run NERO anywhere by typing:
echo   nero
echo.
