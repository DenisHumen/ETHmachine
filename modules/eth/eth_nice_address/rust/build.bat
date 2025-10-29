@echo off
REM Build script для ETH Nice Address Generator (Rust) - Windows

echo ======================================
echo   ETH Nice Address - Rust Builder
echo ======================================
echo.

REM Проверка Cargo
where cargo >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [31mCargo не найден![0m
    echo.
    echo Установите Rust:
    echo   https://rustup.rs/
    echo.
    pause
    exit /b 1
)

echo [32mCargo найден![0m
cargo --version
echo.

REM Переход в директорию скрипта
cd /d "%~dp0"

REM Определение типа сборки
set BUILD_TYPE=%1
if "%BUILD_TYPE%"=="" set BUILD_TYPE=release

if "%BUILD_TYPE%"=="debug" (
    echo [33mСборка в режиме DEBUG[0m
    cargo build
    set BINARY_PATH=target\debug\eth_nice_address.exe
) else (
    echo [32mСборка в режиме RELEASE[0m
    echo [33mПервая компиляция может занять 5-10 минут...[0m
    echo.
    cargo build --release
    set BINARY_PATH=target\release\eth_nice_address.exe
)

echo.
echo [32mКомпиляция завершена![0m
echo.
echo Бинарник: %BINARY_PATH%
echo.
echo Запуск:
echo   %BINARY_PATH% -n 10
echo.
echo Справка:
echo   %BINARY_PATH% --help
echo.

pause
