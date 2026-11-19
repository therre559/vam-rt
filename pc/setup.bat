@echo off
setlocal EnableExtensions
title VaMRT setup
rem =====================================================================
rem  setup.bat - installs the PC side of VaMRT next to this file:
rem    ardy\        NVIDIA's ARDY repo (cloned, pinned to the commit VaMRT was built against) + the VaMRT scripts in ardy\scripts
rem    ardy2bvh\    iremoztrk's ARDY -> BVH converter (cloned; Apache-2.0, pure numpy/scipy)
rem    work\        prompt file, metrics, stream output
rem    config.bat   your settings (written from your answers below; edit any time)
rem  Needs: Git for Windows, Miniconda (or Anaconda) in its default place, an NVIDIA driver that supports CUDA 12 (any driver from
rem  2024 on). No Visual Studio, no CMake: ARDY's optional C++ post-processing is skipped (the stream does not use it).
rem  Models download from Hugging Face on first run: ARDY ~1 GB, the 8-bit text encoder ~8.5 GB. No Hugging Face account needed.
rem  Safe to run again: every step skips what is already there.
rem =====================================================================
set "ROOT=%~dp0"
set "ARDY_COMMIT=e706e27acc88070918308a10922b8f7174d0825e"
where git >nul 2>nul || (echo git is not installed. Install Git for Windows and run this again. & pause & exit /b 1)
set "CONDA_ROOT=%USERPROFILE%\Miniconda3"
if not exist "%CONDA_ROOT%\Scripts\activate.bat" set "CONDA_ROOT=%USERPROFILE%\Anaconda3"
if not exist "%CONDA_ROOT%\Scripts\activate.bat" set "CONDA_ROOT=C:\Miniconda"
if not exist "%CONDA_ROOT%\Scripts\activate.bat" set "CONDA_ROOT=C:\ProgramData\Miniconda3"
if not exist "%CONDA_ROOT%\Scripts\activate.bat" (echo Miniconda was not found. Install it ^(default location^) and run this again. & pause & exit /b 1)
echo Using conda at %CONDA_ROOT%

echo.
echo === 1/5  ARDY (NVIDIA, Apache-2.0) ===
if not exist "%ROOT%ardy\.git" (
  git clone https://github.com/nv-tlabs/ardy "%ROOT%ardy" || goto :gitfail
  git -C "%ROOT%ardy" checkout -q %ARDY_COMMIT% || echo   (could not pin the commit; using the latest - if the stream fails to import, tell us)
)

echo === 2/5  ardy2bvh (converter, Apache-2.0) ===
if not exist "%ROOT%ardy2bvh\.git" git clone https://github.com/iremoztrk/ardy2bvh "%ROOT%ardy2bvh" || goto :gitfail

echo === 3/5  Python environment "ardy" (this is the slow step: PyTorch is ~2.5 GB) ===
call "%CONDA_ROOT%\Scripts\activate.bat"
conda env list | findstr /b /c:"ardy " >nul || conda create -y -n ardy python=3.11
call conda activate ardy
cd /d "%ROOT%ardy"
python -c "import torch" 2>nul || pip install torch torchvision --index-url https://download.pytorch.org/whl/cu126
rem  ARDY itself. ARDY_SKIP_MOTION_CORRECTION=1 is NVIDIA's own switch to skip the C++ extension (needs CMake + Visual Studio
rem  otherwise); it is only used by their foot-skate post-processing, which the stream leaves off.
set "ARDY_SKIP_MOTION_CORRECTION=1"
python -c "import ardy" 2>nul || pip install -e .
rem  what the VaMRT scripts add on top: gradio (encoder service), bitsandbytes (the 8-bit encoder), numpy+scipy (the converter)
pip install "gradio>=6.8" bitsandbytes numpy scipy
rem  the 8-bit text encoder (half the VRAM of NVIDIA's default, and no gated Llama repo to apply for)
python "%ROOT%tools\patch_ardy_int8.py" "%ROOT%ardy\ardy\model\llm2vec\llm2vec_wrapper.py"

echo === 4/5  VaMRT scripts ===
xcopy /y /q "%ROOT%scripts\*" "%ROOT%ardy\scripts\" >nul
if not exist "%ROOT%work" mkdir "%ROOT%work"

echo === 5/5  config.bat ===
if exist "%ROOT%config.bat" (echo   config.bat exists - left alone. & goto :done)
echo.
set "VAMDIR=C:\VaM"
set /p VAMDIR=Your VaM folder (the one with VaM.exe) [C:\VaM]:
set /p KEY=OpenRouter key (or press Enter to fill it in later):
if "%KEY%"=="" set "KEY=PASTE-YOUR-KEY-HERE"
powershell -NoProfile -Command "$c = Get-Content -Raw '%ROOT%config.example.bat'; $c = $c.Replace('set \"VAM_DIR=C:\VaM\"', 'set \"VAM_DIR=%VAMDIR%\"').Replace('PASTE-YOUR-KEY-HERE', '%KEY%').Replace('set \"CONDA_ROOT=%%USERPROFILE%%\Miniconda3\"', 'set \"CONDA_ROOT=%CONDA_ROOT%\"'); Set-Content -NoNewline '%ROOT%config.bat' $c"
echo   wrote config.bat
:done
echo.
echo Done. Next: put VaMRT.NPC.1.var in VaM's AddonPackages, import the Voxta scenario, then run Start_VaMRT.bat. See docs\INSTALL.md.
echo On a second PC for the text encoder: run this same setup.bat there, then Start_Encoder.bat.
pause
exit /b 0

:gitfail
echo.
echo git clone failed (no internet, or GitHub unreachable). Nothing else was done; run setup.bat again when it works.
pause
exit /b 1
