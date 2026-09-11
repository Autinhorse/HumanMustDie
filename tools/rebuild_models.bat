@echo off
rem ------------------------------------------------------------------
rem  Rebuild the character model.
rem  Run this after editing tools/blender/build_swordman.py
rem
rem  Only needed when the MODEL changes (shape / proportions / colors).
rem  Editing code, data or levels does NOT need this.
rem
rem  Usage:  double-click this file,
rem      or  tools\rebuild_models.bat            (rebuild model)
rem      or  tools\rebuild_models.bat --pose     (also render a pose sheet)
rem
rem  Kept ASCII-only on purpose: cmd.exe mis-parses UTF-8 batch files.
rem  All the real work and the Chinese output live in rebuild_models.py
rem ------------------------------------------------------------------
cd /d "%~dp0.."
python tools\rebuild_models.py %*
pause
