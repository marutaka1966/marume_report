#!/bin/bash
# Local TSE regular-close collection. No US equities or funds. No AI-Knowledge writes.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

export TZ="${TZ:-Asia/Tokyo}"
export AI_KNOWLEDGE_PATH="${AI_KNOWLEDGE_PATH:-$HOME/AI-Knowledge}"
unset AI_KNOWLEDGE_TOKEN GITHUB_TOKEN OPENAI_API_KEY || true

mkdir -p "$ROOT/logs"
exec python3 -m v2.collect_jp
