#!/bin/bash
# Double-click this file to check that the trading system is set up correctly.
# It opens a window, runs the setup check, and shows a green/red report.
cd "$(dirname "$0")/module" || { echo "Could not find the module folder."; read -n 1 -s -r; exit 1; }
clear
node doctor.mjs
status=$?
echo ""
if [ "$status" -eq 0 ]; then
  echo "  Everything checks out. You can close this window."
else
  echo "  Some items need fixing — see the red X lines above. Each one tells you how."
  echo "  Fix them, then double-click this file again."
fi
echo ""
echo "  (press any key to close)"
read -n 1 -s -r
