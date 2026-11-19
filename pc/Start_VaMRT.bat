@echo off
setlocal EnableExtensions
title VaMRT launcher

rem =====================================================================
rem  Start_VaMRT.bat - one click: the ARDY motion stream + the motion prompter (two windows).
rem  All settings live in config.bat (copy config.example.bat the first time, or let setup.bat write it).
rem  Then start VaM and Voxta the way you normally do.
rem =====================================================================
if not exist "%~dp0config.bat" goto :missing_config
call "%~dp0config.bat"
set "PROMPT_FILE=%WORK_DIR%\prompt.txt"
if not exist "%WORK_DIR%" mkdir "%WORK_DIR%"
set "VAMRT_PROMPT_FILE=%PROMPT_FILE%"
set "VAMRT_CONVERTER=%CONVERTER%"
set "VAMRT_OUT_DIR=%WORK_DIR%\out"
set "VAMRT_METRICS_FILE=%WORK_DIR%\metrics.tsv"

rem ---------------------------------------------------------------------
rem  Derived paths (no need to edit)
rem ---------------------------------------------------------------------
set "STREAM_OUT=%VAM_DIR%\Saves\Animation\ardy"
set "REQUEST_FILE=%VAM_DIR%\Saves\PluginData\ardy_request.json"
set "WORLD_FILE=%VAM_DIR%\Saves\PluginData\vamrt_world.json"
set "PY=%CONDA_ROOT%\envs\%CONDA_ENV%\python.exe"
set "ACTIVATE=%CONDA_ROOT%\Scripts\activate.bat"

if /i "%~1"=="stream" goto :run_stream
if /i "%~1"=="prompter" goto :run_prompter

:launch
echo ==============================================
echo   VaMRT launcher
echo ==============================================
echo.
if not exist "%ACTIVATE%" goto :missing_conda
if not exist "%PY%" goto :missing_conda
if not exist "%ARDY_DIR%\scripts\ardy_stream.py" goto :missing_ardy
if not exist "%ARDY_DIR%\scripts\motion_prompter.py" goto :missing_ardy
if not exist "%CONVERTER%" goto :missing_converter
if not exist "%VAM_DIR%\Saves" goto :missing_vam
if /i "%MOTION_LLM_KEY%"=="PASTE-YOUR-KEY-HERE" goto :missing_key

if "%TEXT_ENCODER_URL%"=="" goto :encoder_ok
echo Checking the text encoder at %TEXT_ENCODER_URL% ...
"%PY%" -c "import urllib.request;urllib.request.urlopen('%TEXT_ENCODER_URL%',timeout=4);print('  encoder service is up')" 2>nul
if not errorlevel 1 goto :encoder_ok
echo.
echo   The text encoder service did not answer. Start Start_Encoder.bat on the
echo   other PC and wait for "Running on http://0.0.0.0:9550" there. If you go on
echo   without it, the stream loads the encoder on this PC, 8.5 GB of VRAM.
choice /c YN /m "Start anyway"
if errorlevel 2 goto :end
:encoder_ok

echo Checking the language model at %LLM_URL% ...
"%PY%" "%ARDY_DIR%\scripts\motion_prompter.py" --url "%LLM_URL%" --ping
if errorlevel 1 goto :llm_down
goto :llm_ok

:llm_down
echo.
echo The language model did not answer. Check the internet connection and the
echo OpenRouter key at the top of this file. Common requests (sit, stand, dance,
echo walk, wave) still work without it, but anything else will not.
choice /c YN /m "Start anyway"
if errorlevel 2 goto :end

:llm_ok
if not "%RESET_PROMPT%"=="1" goto :reset_done
>"%PROMPT_FILE%" echo A person stands upright.
:reset_done

if not defined VOXTA_EXE goto :voxta_done
for %%I in ("%VOXTA_EXE%") do set "VOXTA_DIR=%%~dpI."
echo Starting Voxta ...
start "Voxta" /d "%VOXTA_DIR%" "%VOXTA_EXE%"
:voxta_done

echo.
echo Starting the ARDY stream ...
start "ARDY stream" cmd /k call "%~f0" stream
timeout /t 3 /nobreak >nul
echo Starting the motion prompter ...
start "Motion prompter" cmd /k call "%~f0" prompter

echo.
echo ----------------------------------------------------------------
echo  Two windows have opened. The stream takes about a minute to load:
echo  it is ready when it prints "Type a prompt to change what the
echo  character does". Then start VaM (and Voxta) as usual.
echo.
echo  To stop everything, close the two windows.
echo ----------------------------------------------------------------
echo.
pause
goto :end

:run_stream
title ARDY stream
call "%ACTIVATE%" "%CONDA_ENV%"
cd /d "%ARDY_DIR%"
python scripts\ardy_stream.py --prompt-file "%PROMPT_FILE%" %STREAM_OPTS% --world-file "%WORLD_FILE%" --converter "%CONVERTER%" --out-dir "%STREAM_OUT%"
echo.
echo The stream has stopped.
pause
goto :end

:run_prompter
title Motion prompter
call "%ACTIVATE%" "%CONDA_ENV%"
cd /d "%ARDY_DIR%"
python scripts\motion_prompter.py --url "%LLM_URL%" --prompt-file "%PROMPT_FILE%" --watch "%REQUEST_FILE%" --world-file "%WORLD_FILE%" %PROMPTER_OPTS%
echo.
echo The motion prompter has stopped.
pause
goto :end

:missing_key
echo The language-model key is not filled in. Edit MOTION_LLM_KEY in config.bat.
goto :fail

:missing_conda
echo Could not find conda or the "%CONDA_ENV%" environment. Looked for:
echo   %ACTIVATE%
echo   %PY%
echo Edit CONDA_ROOT in config.bat (or run setup.bat).
goto :fail

:missing_ardy
echo Could not find ardy_stream.py and motion_prompter.py in:
echo   %ARDY_DIR%\scripts
echo Run setup.bat, or edit ARDY_DIR in config.bat.
goto :fail

:missing_converter
echo Could not find the converter:
echo   %CONVERTER%
echo Run setup.bat, or edit CONVERTER in config.bat.
goto :fail

:missing_vam
echo Could not find your VaM folder (no Saves folder in):
echo   %VAM_DIR%
echo Edit VAM_DIR in config.bat.
goto :fail

:missing_config
echo There is no config.bat next to this file. Run setup.bat once, or copy config.example.bat to config.bat and edit it.
goto :fail

:fail
echo.
pause

:end
endlocal
exit /b
