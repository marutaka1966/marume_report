#!/bin/bash
# Install JP and US LaunchAgents independently. One failure does not skip the other.
set -u

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
jp=0
us=0
bash "$ROOT/scripts/macos/install-jp-schedule.sh" || jp=$?
bash "$ROOT/scripts/macos/install-us-schedule.sh" || us=$?
if [[ "$jp" -ne 0 || "$us" -ne 0 ]]; then
	exit 1
fi
exit 0
