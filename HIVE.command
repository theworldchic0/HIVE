#!/bin/bash
# Double-click (Mac) to start the Hive. First start walks you through every API key,
# then runs the Fib Bee watcher + Trader Bee loop + UI at http://127.0.0.1:8790
cd "$(dirname "$0")"
python3 -m hive start
