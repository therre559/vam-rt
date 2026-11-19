@echo off
setlocal EnableExtensions
title VaMRT text encoder
rem =====================================================================
rem  Start_Encoder.bat - the ARDY text encoder as a small network service (port 9550), for a SECOND PC with a spare GPU
rem  (the 8-bit encoder needs ~8.5 GB of VRAM; a 10 GB card is enough). Run it there; on the VaM PC put
rem  http://<that PC's IP>:9550 into TEXT_ENCODER_URL in config.bat. Ready when it prints "Running on http://0.0.0.0:9550".
rem  On a single 24 GB PC you do not need this: leave TEXT_ENCODER_URL empty and the stream loads the encoder itself.
rem  Needs the same setup.bat install on that PC (it clones ARDY and builds the conda env; the ARDY models are not downloaded
rem  until the stream runs, so the second PC only fetches the encoder). Close the window to stop.
rem =====================================================================
if not exist "%~dp0config.bat" (echo Run setup.bat first, or copy config.example.bat to config.bat. & pause & exit /b 1)
call "%~dp0config.bat"
set "PORT=9550"
set "ACTIVATE=%CONDA_ROOT%\Scripts\activate.bat"
if not exist "%ACTIVATE%" (echo Could not find conda at %CONDA_ROOT%. Edit CONDA_ROOT in config.bat. & pause & exit /b 1)
if not exist "%ARDY_DIR%\scripts\run_text_encoder_server.py" (echo Could not find scripts\run_text_encoder_server.py in %ARDY_DIR%. Run setup.bat, or edit ARDY_DIR in config.bat. & pause & exit /b 1)
call "%ACTIVATE%" "%CONDA_ENV%"
cd /d "%ARDY_DIR%"
set "TEXT_ENCODER_TMP_FOLDER=%TEMP%\text_encoder"
rem  the 8-bit encoder - the same one the stream uses (ardy_to_vam.py: INT8_REPO); remove this line for NVIDIA's bf16 one (15 GB, gated)
set "ARDY_TEXT_ENCODER_INT8=voxta/Llama-3-8B-LLM2Vec-ARDY-INT8"
echo Loading the text encoder (a few minutes the first time: 8.5 GB download) ...
python scripts\run_text_encoder_server.py --host 0.0.0.0 --port %PORT%
echo.
echo The encoder service has stopped.
pause
endlocal
