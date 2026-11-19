@echo off
rem =====================================================================
rem  VaMRT config - copy this file to config.bat and fill in YOUR paths. config.bat is yours (it holds your API key)
rem  and is never shared; config.example.bat is the template that ships.
rem =====================================================================

rem Where setup.bat put things (defaults match setup.bat; change only if you moved them)
set "VAMRT_ROOT=%~dp0"
set "CONDA_ROOT=%USERPROFILE%\Miniconda3"
set "CONDA_ENV=ardy"
set "ARDY_DIR=%VAMRT_ROOT%ardy"
set "CONVERTER=%VAMRT_ROOT%ardy2bvh\ardy2bvh.py"
set "WORK_DIR=%VAMRT_ROOT%work"

rem Your VaM folder (the one with VaM.exe and a Saves folder)
set "VAM_DIR=C:\VaM"

rem The language model the motion prompter uses (any OpenAI-compatible endpoint). OpenRouter is the easy route:
rem paste the same key you gave Voxta. KoboldCpp / LM Studio / Ollama work too (set MOTION_LLM_KEY to anything).
set "LLM_URL=https://openrouter.ai/api/v1"
set "MOTION_LLM_KEY=PASTE-YOUR-KEY-HERE"
set "MOTION_LLM_MODEL=sao10k/l3.1-euryale-70b"

rem The text encoder. SINGLE PC: leave this empty and the stream loads the encoder itself (about 8.5 GB of VRAM on top of
rem ARDY's 6 GB - a 24 GB card is fine, a 12 GB card is not). SECOND PC: run Start_Encoder.bat there and put its address here.
set "TEXT_ENCODER_URL="

rem Stream settings. --playback-speed must match the BVH Player's Speed (%%) in VaM: 0.9 = 90.
set "STREAM_OPTS=--history 40 --cfg-text 3 --hold-settle 2 --playback-speed 0.9 --steps 6 --move-speed 0.8 --move-accel 0.6 --commit-frames 16 --chunk-seconds 0.8"
set "PROMPTER_OPTS="

rem 1 = every launch starts with her standing still
set "RESET_PROMPT=1"
rem Optional: full path of Voxta.Server.exe to start it too
set "VOXTA_EXE="
