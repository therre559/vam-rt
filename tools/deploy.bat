@echo off
rem Copies the repo files to where they actually run. Edit the two paths for your machine.
set "ARDY_SCRIPTS=C:\Users\Todd Herre\Desktop\ardy-main\ardy-main\scripts"
set "VAM_SCRIPTS=C:\Users\Todd Herre\Desktop\New folder (4)\Custom\Scripts"
set "REPO=%~dp0.."
copy /Y "%REPO%\server\*.py" "%ARDY_SCRIPTS%\"
copy /Y "%REPO%\server\verified_prompts.json" "%ARDY_SCRIPTS%\" 2>nul
copy /Y "%REPO%\plugin\legacy\BVHPlayer_autoreload.cs" "%VAM_SCRIPTS%\"
echo Done.
