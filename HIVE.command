#!/bin/bash
# Double-click (Mac) to start the Hive: Fib Bee watcher + Trader Bee loop + UI at http://127.0.0.1:8790
cd "$(dirname "$0")"
( sleep 3; open "http://127.0.0.1:8790" ) &
python3 -m hive start
