#!/bin/bash
# Double-click (Mac): the API-key walkthrough on its own (add / replace / re-test keys), then the doctor.
cd "$(dirname "$0")"
python3 -m hive setup
python3 -m hive doctor
read -n 1 -s -r -p "Press any key to close"
