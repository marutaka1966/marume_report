#!/bin/bash
# One-command install for Mac local fund collection. Beginner-safe.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LABEL="com.marume.collect-funds"
TEMPLATE="$ROOT/scripts/macos/${LABEL}.plist.template"
RUN_SCRIPT="$ROOT/scripts/macos/run-collect-funds.sh"
DEST_DIR="${LAUNCH_AGENTS_DIR:-$HOME/Library/LaunchAgents}"
DEST="$DEST_DIR/${LABEL}.plist"
KNOWLEDGE="${AI_KNOWLEDGE_PATH:-$HOME/AI-Knowledge}"

reject_knowledge() {
	case "$1" in
		*AI-Knowledge*|*Holdings.md*)
			echo "error: will not write into AI-Knowledge or Holdings.md" >&2
			exit 1
			;;
	esac
}

if [[ ! -f "$TEMPLATE" || ! -f "$RUN_SCRIPT" ]]; then
	echo "error: install files are missing" >&2
	exit 1
fi

reject_knowledge "$DEST"
reject_knowledge "$ROOT"
mkdir -p "$DEST_DIR" "$ROOT/logs"
chmod +x "$RUN_SCRIPT" "$ROOT/scripts/macos/install-fund-schedule.sh" "$ROOT/scripts/macos/uninstall-fund-schedule.sh"

sed \
	-e "s|__REPO_ROOT__|${ROOT}|g" \
	-e "s|__RUN_SCRIPT__|${RUN_SCRIPT}|g" \
	-e "s|__AI_KNOWLEDGE_PATH__|${KNOWLEDGE}|g" \
	"$TEMPLATE" > "$DEST"

if [[ "${SKIP_LAUNCHCTL:-}" != "1" ]]; then
	uid="$(id -u)"
	launchctl bootout "gui/${uid}" "$DEST" >/dev/null 2>&1 || true
	launchctl bootout "gui/${uid}/${LABEL}" >/dev/null 2>&1 || true
	if ! launchctl bootstrap "gui/${uid}" "$DEST" >/dev/null 2>&1; then
		launchctl load -w "$DEST"
	fi
fi

echo "投信の自動収集を登録しました。"
echo "毎日 21:00 と 10:30（Macのタイムゾーンを日本時間にしてください）に実行します。"
echo "スリープ中に時刻を過ぎた場合は、起動後に実行されます。"
echo "解除: ${ROOT}/scripts/macos/uninstall-fund-schedule.sh"
