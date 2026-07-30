@echo off
chcp 65001 >nul
title AI 网络安全管家 - 安装程序

echo.
echo ╔══════════════════════════════════════════╗
echo ║    🛡️  AI 网络安全管家 - 一键安装程序    ║
echo ╚══════════════════════════════════════════╝
echo.

:: 检查管理员权限
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo ⚠️  建议以管理员身份运行以获得完整功能
    echo.
    echo 右键此文件 → "以管理员身份运行"
    echo.
    choice /c YN /m "是否继续以普通权限安装"
    if errorlevel 2 exit /b
)

echo [1/5] 检查 Python 环境...
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ 未检测到 Python!
    echo.
    echo 请先安装 Python 3.10+:
    echo   1. 打开 https://www.python.org/downloads/
    echo   2. 下载并安装，勾选 "Add Python to PATH"
    echo   3. 重新运行此安装程序
    pause
    exit /b 1
)

python --version
echo ✅ Python 环境正常

echo.
echo [2/5] 升级 pip...
python -m pip install --upgrade pip --quiet

echo.
echo [3/5] 安装依赖包 (可能需要几分钟)...
cd /d "%~dp0..\pc_agent"
pip install -r requirements.txt

if %errorlevel% neq 0 (
    echo.
    echo ⚠️  部分依赖安装可能失败
    echo 基础功能仍可使用，但部分高级功能受限
    echo.
)

echo.
echo [4/5] 检测 ESP32 设备...
python -c "import serial.tools.list_ports; ports=list(serial.tools.list_ports.comports()); print(f'找到 {len(ports)} 个串口'); [print(f'  {p.device}: {p.description}') for p in ports]"

echo.
echo [5/5] 创建桌面快捷方式...

:: 创建启动脚本
set "START_SCRIPT=%~dp0..\start_guardian.bat"
(
echo @echo off
echo cd /d "%~dp0..\pc_agent"
echo python main.py
echo pause
) > "%START_SCRIPT%"

:: 创建快捷方式
powershell -Command "$WS = New-Object -ComObject WScript.Shell; $SC = $WS.CreateShortcut([Environment]::GetFolderPath('Desktop') + '\AI安全管家.lnk'); $SC.TargetPath = '%START_SCRIPT%'; $SC.WorkingDirectory = '%~dp0..\pc_agent'; $SC.IconLocation = '%~dp0..\pc_agent\shield.ico,0'; $SC.Description = 'AI 网络安全管家'; $SC.Save()" 2>nul

echo.
echo ╔══════════════════════════════════════════╗
echo ║         ✅ 安装完成!                      ║
echo ║                                          ║
echo ║   📟 桌面已创建 "AI安全管家" 快捷方式      ║
echo ║   🌐 Web Dashboard: http://127.0.0.1:5000 ║
echo ║   📋 日志文件: pc_agent\guardian.log      ║
echo ║                                          ║
echo ║   现在可以双击桌面快捷方式启动!             ║
echo ╚══════════════════════════════════════════╝
echo.
echo 提示: 请确保 ESP32 已通过 USB 连接电脑
echo.
pause
