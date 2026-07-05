@echo off
chcp 65001 >nul
title AI 网络安全管家
cd /d "%~dp0pc_agent"
echo.
echo ╔══════════════════════════════════════╗
echo ║  🛡️  AI 网络安全管家 v1.0            ║
echo ║  AI Network Security Guardian       ║
echo ╚══════════════════════════════════════╝
echo.
echo 🌐 Web Dashboard: http://127.0.0.1:5000
echo 📟 请确认 ESP32 已连接
echo.
echo 启动中...
echo.
python main.py %*
pause
