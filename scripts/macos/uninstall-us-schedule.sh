#!/bin/bash
# One-command uninstall for Mac local US close collection. Beginner-safe.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LABEL="com.marume.collect-us"
DEST_DIR="${LAUNCH_AGENTS_DIR:-$HOME/Library/LaunchAgents}"
DEST="$DEST_DIR/${LABEL}.plist"

case "$DEST" in
	*AI-Knowledge*|*Holdings.md*)
		echo "error: will not touch AI-Knowledge or Holdings.md" >&2
		exit 1
		;;
esac

if [[ "${SKIP_LAUNCHCTL:-}" != "1" ]]; then
	uid="$(id -u)"
	launchctl bootout "gui/${uid}" "$DEST" >/dev/null 2>&1 || true
	launchctl bootout "gui/${uid}/${LABEL}" >/dev/null 2>&1 || true
	if [[ -f "$DEST" ]]; then
		launchctl unload -w "$DEST" >/dev/null 2>&1 || true
	fi
fi

rm -f "$DEST"
echo "米国株の自動収集を解除しました。"
echo "リポジトリの logs/ はそのまま残ります。"
