@echo off
rem 创建时间: 2026-09-10
rem 功能: 无控制台窗口启动 Codex 用量悬浮窗
rem 用法: 双击运行; 开机自启可将本文件快捷方式放入 shell:startup

cd /d "%~dp0"
start "" pythonw main.py
