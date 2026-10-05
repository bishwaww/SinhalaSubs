@echo off
rem Build everything: tests -> SinhalaSubs.exe -> SinhalaSubs-Setup-<version>.exe (in dist\)
cd /d "%~dp0"

echo === 1/4 Tests
.venv\Scripts\python -m pytest -q || goto :fail

echo === 2/4 SinhalaSubs.exe
.venv\Scripts\pyinstaller SinhalaSubs.spec --noconfirm --log-level WARN || goto :fail

echo === 3/4 Self-test of the packed app
dist\SinhalaSubs\SinhalaSubs.exe --selftest
if errorlevel 1 (type "%TEMP%\sinhalasubs_selftest.txt" & goto :fail)

echo === 4/4 Installer
for /f "tokens=2 delims==" %%v in ('findstr /b "__version__" sinhalasubs\__init__.py') do set VERSION=%%~v
set VERSION=%VERSION: =%
set VERSION=%VERSION:"=%
"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" /Q /DMyAppVersion=%VERSION% installer\SinhalaSubs.iss || goto :fail

echo.
echo Done: dist\SinhalaSubs-Setup-%VERSION%.exe
exit /b 0

:fail
echo.
echo BUILD FAILED
exit /b 1
