# What to update for 0.3.2
1. Unzip over the repo, then run tools\deploy.bat (copies the plugin, the BVH Player and the Python scripts).
2. In VaM reload BOTH plugins on the Person atom: VaMRT_Senses and BVHPlayer_autoreload.
   (The BVH Player's new defaults only apply to a freshly added plugin or to a scene that did not store its own values.)
3. Nothing changes in Voxta or the prompter.
4. To test reactions without Timeline: On Stare > atom Person > plugin VaMRT.Senses > action "Send snapshot now", then "Test: On Stare".
