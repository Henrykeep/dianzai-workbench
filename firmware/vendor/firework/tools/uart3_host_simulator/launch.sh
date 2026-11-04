#!/usr/bin/env bash
set -eu

simulator_dir="/home/qianmo/workspace_ccstheia/freertos_firework/tools/uart3_host_simulator"
exec /usr/bin/python3 "${simulator_dir}/server.py" \
    --open-browser \
    --serial-port /dev/ttyACM0
