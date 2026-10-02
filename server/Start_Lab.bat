@echo off
setlocal EnableExtensions
title ARDY motion lab launcher

rem =====================================================================
rem  Start_Lab.bat - one click start for the ARDY motion lab
rem
rem  Opens two windows:
rem    1) ARDY stream  (the same stream, plus a log of what it measures)
rem    2) Motion lab   (plays candidate wordings, asks you to rate them)
rem  Start VaM yourself and keep the character in view. Voxta is not needed.
rem  Close the normal Start_ARDY windows first: only one stream can run.
rem =====================================================================
set "CONDA_ROOT=C:\Users\Todd Herre\Miniconda3"
set "CONDA_ENV=ardy"
set "ARDY_DIR=C:\Users\Todd Herre\Desktop\ardy-main\ardy-main"
set "VAM_DIR=C:\Users\Todd Herre\Desktop\New folder (4)"
set "CONVERTER=C:\ARDY2BVH\ardy2bvh-main\ardy2bvh.py"
set "PROMPT_FILE=C:\ARDY2BVH\prompt.txt"
set "METRICS_FILE=C:\ARDY2BVH\metrics.tsv"
set "STREAM_OPTS=--history 40 --cfg-text 3"

rem  Try these ONE AT A TIME (they come from the ARDY paper). Keep this line identical in Start_ARDY.bat and
rem  Start_Lab.bat: wordings verified in the lab depend on these settings.
rem    --history 160   longer memory: the model supports 8 seconds, 40 frames is only 2 seconds
rem    --steps 5       fewer denoising steps: faster and lighter on the GPU, a little less accurate (default 10)
rem    --cfg-text 4    stronger text guidance: may wake up wordings that currently do nothing
rem    --model core8 --chunk-seconds 0.8   the 8-frame model: reacts in under a second, slightly lower quality

rem  Which suite to test: dance, dance2, poses, idle, gestures, extras, all (or several, comma separated)
set "LAB_SUITE=dance"
rem  Extra lab options. Examples:  --only dance.sexy     --redo     --suite gestures
set "LAB_OPTS="

set "STREAM_OUT=%VAM_DIR%\Saves\Animation\ardy"
set "ACTIVATE=%CONDA_ROOT%\Scripts\activate.bat"

if /i "%~1"=="stream" goto :run_stream
if /i "%~1"=="lab" goto :run_lab

:launch
echo ==============================================
echo   ARDY motion lab
echo ==============================================
echo.
if not exist "%ACTIVATE%" goto :missing_conda
if not exist "%ARDY_DIR%\scripts\ardy_stream.py" goto :missing_files
if not exist "%ARDY_DIR%\scripts\ardy_lab.py" goto :missing_files
if not exist "%CONVERTER%" goto :missing_converter

>"%PROMPT_FILE%" echo A person stands upright.
if exist "%METRICS_FILE%" del "%METRICS_FILE%"

echo Starting the stream ...
start "ARDY stream (lab)" cmd /k call "%~f0" stream
timeout /t 3 /nobreak >nul
echo Starting the lab ...
start "Motion lab" cmd /k call "%~f0" lab

echo.
echo ----------------------------------------------------------------
echo  Two windows have opened. The stream needs about a minute to load;
echo  the lab waits for it and then starts on its own.
echo.
echo  Open VaM and keep the character in view. For each wording the lab
echo  plays it, shows how much she moved, and asks you to rate it:
echo     g = good   o = ok   b = bad   r = replay   s = skip   q = quit
echo  Wordings that make her stand still are discarded automatically.
echo  What you rate good is saved and used by the motion prompter.
echo  Restart Start_ARDY.bat afterwards to pick it up.
echo ----------------------------------------------------------------
echo.
pause
goto :end

:run_stream
title ARDY stream (lab)
call "%ACTIVATE%" "%CONDA_ENV%"
cd /d "%ARDY_DIR%"
python scripts\ardy_stream.py --prompt-file "%PROMPT_FILE%" %STREAM_OPTS% --converter "%CONVERTER%" --out-dir "%STREAM_OUT%" --metrics-file "%METRICS_FILE%"
echo.
echo The stream has stopped.
pause
goto :end

:run_lab
title Motion lab
call "%ACTIVATE%" "%CONDA_ENV%"
cd /d "%ARDY_DIR%"
python scripts\ardy_lab.py --prompt-file "%PROMPT_FILE%" --metrics-file "%METRICS_FILE%" --suite %LAB_SUITE% --start-wait 240 %LAB_OPTS%
echo.
echo The lab has finished. You can close this window.
pause
goto :end

:missing_conda
echo Could not find conda at:
echo   %ACTIVATE%
echo Edit CONDA_ROOT at the top of this file.
goto :fail

:missing_files
echo Could not find ardy_stream.py and ardy_lab.py in:
echo   %ARDY_DIR%\scripts
echo Put both files there, or edit ARDY_DIR at the top of this file.
goto :fail

:missing_converter
echo Could not find the converter:
echo   %CONVERTER%
echo Edit CONVERTER at the top of this file.
goto :fail

:fail
echo.
pause

:end
endlocal
exit /b
