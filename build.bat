@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

REM ============================================================
REM  因私出国（境）人员审批管理系统 — Windows 打包脚本
REM  产出：dist\POTMS.exe（单文件，约 12-15 MB）
REM  用法：双击运行，或在命令行执行 build.bat
REM ============================================================

cd /d "%~dp0"

echo ============================================================
echo   POTMS 打包脚本
echo   工作目录: %CD%
echo ============================================================
echo.

REM ---- 1. 检查 Python ----
where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3.12+ 并加入 PATH。
    pause
    exit /b 1
)
for /f "delims=" %%v in ('python --version') do echo [信息] 检测到 %%v

REM ---- 2. 安装依赖 + PyInstaller ----
echo.
echo [步骤] 安装项目依赖与 PyInstaller ...
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo [错误] 依赖安装失败。
    pause
    exit /b 1
)
python -m pip install pyinstaller
if errorlevel 1 (
    echo [错误] PyInstaller 安装失败。
    pause
    exit /b 1
)

REM ---- 3. 清理旧产物 ----
echo.
echo [步骤] 清理旧的 build/ dist/ ...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist POTMS.spec del /q POTMS.spec

REM ---- 4. 打包 ----
echo.
echo [步骤] 开始打包（首次较慢，请耐心等待）...
pyinstaller --onefile ^
  --name "POTMS" ^
  --add-data "templates;templates" ^
  --add-data "static;static" ^
  --hidden-import bcrypt ^
  --hidden-import waitress ^
  --exclude-module cryptography ^
  app.py
if errorlevel 1 (
    echo.
    echo [错误] 打包失败，请查看上方日志。
    echo        若报缺少模块，可在本脚本的 pyinstaller 命令中追加 --collect-all ^<模块名^>。
    pause
    exit /b 1
)

REM ---- 5. 完成 ----
echo.
echo ============================================================
echo   打包完成！
echo   可执行文件: %CD%\dist\POTMS.exe
echo.
echo   部署提示：
echo   - 将 POTMS.exe 拷贝到有写权限的目录（如 D:\POTMS\）运行。
echo   - 首次运行自动创建 data.db / uploads / exports / backup / .secret_key
echo     于 exe 同目录；默认管理员 admin / admin123，请尽快改密。
echo   - 默认以 waitress 生产服务器运行，访问 http://localhost:5000
echo   - 如需局域网访问：设置环境变量 POTMS_HOST=0.0.0.0
echo ============================================================
echo.
pause
endlocal
