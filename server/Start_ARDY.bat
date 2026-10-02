@echo off
setlocal EnableExtensions
title ARDY launcher

rem =====================================================================
rem  Start_ARDY.bat - one click start for the ARDY motion pipeline
rem
rem  Opens two windows:
rem    1) ARDY stream     (generates the motion and feeds it to VaM)
rem    2) Motion prompter (turns Voxta's requests into motion prompts)
rem  Start VaM and Voxta the way you normally do.
rem
rem  SETTINGS - the only part you should need to edit
rem =====================================================================
set "CONDA_ROOT=C:\Users\Todd Herre\Miniconda3"
set "CONDA_ENV=ardy"
set "ARDY_DIR=C:\Users\Todd Herre\Desktop\ardy-main\ardy-main"
set "VAM_DIR=C:\Users\Todd Herre\Desktop\New folder (4)"
set "CONVERTER=C:\ARDY2BVH\ardy2bvh-main\ardy2bvh.py"
set "PROMPT_FILE=C:\ARDY2BVH\prompt.txt"
set "LLM_URL=http://192.168.0.103:5001/v1"
set "STREAM_OPTS=--history 40 --cfg-text 3"

rem  Try these ONE AT A TIME (they come from the ARDY paper). Keep this line identical in Start_ARDY.bat and
rem  Start_Lab.bat: wordings verified in the lab depend on these settings.
rem    --history 160   longer memory: the model supports 8 seconds, 40 frames is only 2 seconds
rem    --steps 5       fewer denoising steps: faster and lighter on the GPU, a little less accurate (default 10)
rem    --cfg-text 4    stronger text guidance: may wake up wordings that currently do nothing
rem    --model core8 --chunk-seconds 0.8   the 8-frame model: reacts in under a second, slightly lower quality

rem  Extra options for the motion prompter. Example: --styles (experimental: lets "sexy dance" use styled wording)
set "PROMPTER_OPTS="

rem  1 = every launch starts with her standing still (instead of whatever the
rem  prompt file held last time). 0 = leave the prompt file alone.
set "RESET_PROMPT=1"

rem  Optional: full path of the program that starts Voxta. Leave empty to skip.
rem  Example: set "VOXTA_EXE=C:\Voxta\Voxta.Server.exe"
set "VOXTA_EXE="

rem ---------------------------------------------------------------------
rem  Derived paths (no need to edit)
rem ---------------------------------------------------------------------
set "STREAM_OUT=%VAM_DIR%\Saves\Animation\ardy"
set "REQUEST_FILE=%VAM_DIR%\Saves\PluginData\ardy_request.json"
set "PY=%CONDA_ROOT%\envs\%CONDA_ENV%\python.exe"
set "ACTIVATE=%CONDA_ROOT%\Scripts\activate.bat"

if /i "%~1"=="stream" goto :run_stream
if /i "%~1"=="prompter" goto :run_prompter

:launch
echo ==============================================
echo   ARDY launcher
echo ==============================================
echo.
if not exist "%ACTIVATE%" goto :missing_conda
if not exist "%PY%" goto :missing_conda
if not exist "%ARDY_DIR%\scripts\ardy_stream.py" goto :missing_ardy
if not exist "%ARDY_DIR%\scripts\motion_prompter.py" goto :missing_ardy
if not exist "%CONVERTER%" goto :missing_converter
if not exist "%VAM_DIR%\Saves" goto :missing_vam

echo Checking the language model at %LLM_URL% ...
"%PY%" "%ARDY_DIR%\scripts\motion_prompter.py" --url "%LLM_URL%" --ping
if errorlevel 1 goto :llm_down
goto :llm_ok

:llm_down
echo.
echo The language model did not answer. Her PC may be asleep, or KoboldCpp
echo may not be running. Common requests (sit, stand, dance, walk, wave) still
echo work without it, but anything else will not.
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
python scripts\ardy_stream.py --prompt-file "%PROMPT_FILE%" %STREAM_OPTS% --converter "%CONVERTER%" --out-dir "%STREAM_OUT%"
echo.
echo The stream has stopped.
pause
goto :end

:run_prompter
title Motion prompter
call "%ACTIVATE%" "%CONDA_ENV%"
cd /d "%ARDY_DIR%"
python scripts\motion_prompter.py --url "%LLM_URL%" --prompt-file "%PROMPT_FILE%" --watch "%REQUEST_FILE%" %PROMPTER_OPTS%
echo.
echo The motion prompter has stopped.
pause
goto :end

:missing_conda
echo Could not find conda or the "%CONDA_ENV%" environment. Looked for:
echo   %ACTIVATE%
echo   %PY%
echo Edit CONDA_ROOT at the top of this file.
goto :fail

:missing_ardy
echo Could not find ardy_stream.py and motion_prompter.py in:
echo   %ARDY_DIR%\scripts
echo Put both files there, or edit ARDY_DIR at the top of this file.
goto :fail

:missing_converter
echo Could not find the converter:
echo   %CONVERTER%
echo Edit CONVERTER at the top of this file.
goto :fail

:missing_vam
echo Could not find your VaM folder (no Saves folder in):
echo   %VAM_DIR%
echo Edit VAM_DIR at the top of this file.
goto :fail

:fail
echo.
pause

:end
endlocal
exit /b
