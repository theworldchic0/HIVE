#!/bin/zsh
# TRADING DASHBOARD launcher — double-click me.
# Starts the dashboard server on http://127.0.0.1:8789 and opens the page.
#
# DISARMED by default (safe): every trade action is forced to a dry-run preview.
# To allow REAL order placement from the Trade Idea panel, run with ARM=1:
#     ARM=1 ~/Desktop/Altcoin-Trading-System/TRADING-DASHBOARD.command
# Even armed, every trade requires an explicit per-trade confirm in the UI,
# the per-order USD cap, and a registry-vetted token.

HERE="$(cd "$(dirname "$0")" && pwd)"
COCKPIT="$HERE/cockpit"
URL="http://127.0.0.1:8789/"
LOG="$HOME/Library/Logs/trading-dashboard.log"

cd "$COCKPIT" || { echo "cockpit folder missing at $COCKPIT"; exit 1; }

ARMFLAG=""
[ "$ARM" = "1" ] && ARMFLAG="TRADE_IDEA_ARMED=1"

if lsof -nP -iTCP:8789 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "dashboard server already running on 8789."
else
  echo "starting dashboard server… (log: $LOG)"
  if [ "$ARM" = "1" ]; then
    nohup env TRADE_IDEA_ARMED=1 node dashboard-server.mjs >> "$LOG" 2>&1 &
  else
    nohup node dashboard-server.mjs >> "$LOG" 2>&1 &
  fi
  for i in {1..20}; do
    lsof -nP -iTCP:8789 -sTCP:LISTEN >/dev/null 2>&1 && break
    sleep 0.5
  done
fi

STATE=$(curl -s --max-time 4 "http://127.0.0.1:8789/api/trade-idea/config" | grep -o '"armed":true')
if [ -n "$STATE" ]; then
  echo "server is ARMED (live trade path enabled; per-trade confirm still required)."
else
  echo "server is DISARMED (dry-run only — previews, no real orders)."
fi

# The dashboard is developed against Chrome — open it there when installed,
# so your default browser stays yours for everything else.
if open -Ra "Google Chrome" 2>/dev/null; then
  open -a "Google Chrome" "$URL"
else
  open "$URL"
  echo "tip: the dashboard is built and tested against Chrome — https://www.google.com/chrome"
fi
echo "Dashboard: $URL   (first data scan can take ~30s — the page fills in as it lands)"
