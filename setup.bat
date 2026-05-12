@echo off
echo ============================================================
echo  SAMAY Monitor - Instalacion
echo ============================================================
echo.

:: Verificar Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python no esta instalado o no esta en el PATH.
    echo Descargalo de https://python.org
    pause
    exit /b 1
)
echo [OK] Python encontrado

:: Instalar dependencias
echo.
echo Instalando dependencias...
pip install requests python-dotenv --quiet
if errorlevel 1 (
    echo ERROR: No se pudieron instalar las dependencias.
    pause
    exit /b 1
)
echo [OK] Dependencias instaladas

:: Crear .env si no existe
if not exist ".env" (
    if exist ".env.example" (
        copy ".env.example" ".env" >nul
        echo [OK] Archivo .env creado desde .env.example
        echo.
        echo IMPORTANTE: Abri el archivo .env y completa con tus valores reales.
        echo Presiona cualquier tecla cuando hayas completado el .env...
        notepad .env
        pause >nul
    ) else (
        echo ERROR: No se encontro .env.example
        pause
        exit /b 1
    )
) else (
    echo [OK] Archivo .env ya existe
)

:: Probar el script
echo.
echo Probando conexion con Meta Ads...
python samay_monitor.py
if errorlevel 1 (
    echo.
    echo ERROR: El script fallo. Revisa el .env y volvé a correr setup.bat
    pause
    exit /b 1
)

:: Registrar en el Programador de Tareas
echo.
echo Configurando tarea automatica cada hora...

set SCRIPT_DIR=%~dp0
set TASK_NAME=SamayMonitor

:: Eliminar tarea anterior si existe
schtasks /delete /tn "%TASK_NAME%" /f >nul 2>&1

:: Crear la tarea (corre cada hora)
schtasks /create /tn "%TASK_NAME%" /tr "cmd /c cd /d \"%SCRIPT_DIR%\" && python samay_monitor.py >> samay.log 2>&1" /sc hourly /mo 1 /st 00:00 /ru "%USERNAME%" /f

if errorlevel 1 (
    echo ERROR: No se pudo crear la tarea automatica.
    echo Abrí el Programador de Tareas manualmente.
) else (
    echo [OK] Tarea creada: corre cada hora automaticamente
)

echo.
echo ============================================================
echo  SAMAY Monitor instalado correctamente!
echo  - Logs: %SCRIPT_DIR%samay.log
echo  - Para ver la tarea: Programador de Tareas -> SamayMonitor
echo ============================================================
echo.
pause
