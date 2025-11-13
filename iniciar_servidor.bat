@echo off
echo ========================================
echo  🚀 SERVIDOR NOTARIA - Permisos de Viaje
echo ========================================

REM Activar entorno virtual
call .venv\Scripts\activate

REM Obtener IP local
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4" ^| findstr /v "127.0.0.1"') do set IP=%%a

echo.
echo 📡 Servidor iniciando...
echo.
echo 🖥️  Acceso LOCAL (desde esta PC):
echo     http://localhost:8501
echo.
echo 🌐 Acceso RED (desde otras PCs):
echo     http://%IP%:8501
echo.
echo 📋 Comparte esta URL con tu equipo:
echo     http://%IP%:8501
echo.
echo ⚠️  Presiona Ctrl+C para detener el servidor
echo ========================================

REM Iniciar Streamlit
streamlit run app.py

pause