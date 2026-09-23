@echo off
REM ==========================================================
REM  Chay chatbot Vat ly 12 chi bang cach double-click file nay.
REM  Khong can mo terminal / go lenh nua.
REM ==========================================================

cd /d "%~dp0"

if not exist venv (
    echo Khong tim thay thu muc venv. Hay chay lan dau theo huong dan README.md truoc.
    pause
    exit /b
)

call venv\Scripts\activate.bat
streamlit run app.py

REM Giu cua so lai neu co loi, de ban doc duoc thong bao
pause
