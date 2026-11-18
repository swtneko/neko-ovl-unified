@echo off
title Neko Overlay Studio (Unified FreeMode + MultiPK)
chcp 65001 >nul
echo ========================================================
echo    🐱 NEKO OVERLAY STUDIO (FREEMODE + MULTIPK)
echo ========================================================
echo.
echo Đang kiểm tra thư viện...
pip install -r requirements.txt
echo.
echo Khởi động Server tại cổng 8000...
echo Control Dashboard: http://localhost:8000/control
echo.
python server.py
pause
